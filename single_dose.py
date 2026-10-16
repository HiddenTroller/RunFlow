"""공식 용법의 1회 정수 상한을 자동 적용하는 성인 1회 가정 비교. 수량 입력을 받지 않는다."""
import copy
import html
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser

from calculator import number, to_mg
from mfds_client import ServiceError
from normalization import normalize_name

SOURCE = 'https://www.data.go.kr/data/15095677/openapi.do'
NOTICE = ('각 제품을 공식 성인 용법의 최대 1회 수량만큼 함께 복용하는 가정입니다. '
          '실제 복용량이나 복용 권고가 아니며, 기준 이내도 병용 안전을 뜻하지 않습니다. '
          '하루 횟수·복용 간격·1일 최대량은 이번 1회 계산에 사용하지 않습니다.')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('p', 'div', 'br', 'article', 'section', 'paragraph', 'li', 'tr'):
            self.parts.append('\n')
        for key, value in attrs:
            if key.lower() == 'title' and value:
                self.parts.append(value + ' ')

    def handle_data(self, data):
        self.parts.append(data)


def document_text(value):
    parser = _Text()
    parser.feed(html.unescape(value if isinstance(value, str) else ''))
    text = unicodedata.normalize('NFKC', ''.join(parser.parts))
    return '\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip())


COUNT = re.compile(r'1\s*회\s*(?P<low>[0-9]+)(?:\s*[~～∼〜\-–—]\s*(?P<high>[0-9]+))?\s*(?P<unit>정|캡슐)')
OTHER_COHORT = re.compile(r'(?:소아|어린이)\s*[:：]|(?:만\s*)?[0-9]+\s*(?:~\s*[0-9]+\s*)?세\s*(?:미만|이하)')


def extract_single_count(value, expected_unit):
    """1회 1~2정 -> 2정. 성인 구간만 읽으며 일일 최대 정수/포장 수량은 무시한다."""
    if expected_unit not in ('정', '캡슐'):
        return {'status': 'unknown', 'reason': '정제·캡슐 외 제형은 자동 정수 해석 대상이 아닙니다.'}
    lines = document_text(value).splitlines()
    candidates = []
    for index, line in enumerate(lines):
        adult = re.search(r'성인', line)
        if not adult:
            continue
        # 같은 문장의 소아 구간을 성인 용법으로 쓰지 않는다.
        section = line[adult.start():]
        if not COUNT.search(section):
            for following in lines[index + 1:index + 4]:
                if re.search(r'성인|소아\s*[:：]|어린이\s*[:：]', following) or OTHER_COHORT.search(following):
                    break
                section += ' ' + following
                if COUNT.search(section):
                    break
        boundary = OTHER_COHORT.search(section)
        if boundary:
            section = section[:boundary.start()]
        if re.search(r'체중|\bkg\b|초회|첫날|유지량|투석|신장애|간장애|고령자|또는|혹은', section, re.I):
            continue
        matches = list(COUNT.finditer(section))
        if len(matches) != 1:
            continue
        match = matches[0]
        low, high = int(match['low']), int(match['high'] or match['low'])
        if match['unit'] != expected_unit or not 0 < low <= high <= 100:
            continue
        # 1회 정수의 뒤에 미완성 범위/소수가 있는 문장은 허용하지 않는다.
        if re.search(r'1\s*회\s*[0-9]+\s*[.,/]', section):
            continue
        candidates.append({'status': 'known', 'quantity': str(high), 'quantity_min': str(low),
                           'quantity_max': str(high), 'unit': expected_unit,
                           'evidence': section.strip(), 'count_text': match.group(0),
                           'policy': 'official_single_dose_upper_bound', 'population': 'adult'})
    unique = {tuple(sorted(item.items())): item for item in candidates}
    if len(unique) != 1:
        return {'status': 'unknown', 'reason': '공식 성인 용법의 1회 정수가 없거나 적용 문장이 여러 개입니다.'}
    return next(iter(unique.values()))


def ingredient_key(ingredient):
    code = str(ingredient.get('ingredient_code') or '').strip()
    return 'code:' + code if code else 'name:' + normalize_name(ingredient.get('name', ''))


def release_class(product):
    text = str(product.get('name', '')) + ' ' + document_text(product.get('directions_text', ''))
    if re.search(r'서방|장용|지속성|이알|(?<![A-Za-z])(?:ER|SR|XR|CR|MR)(?![A-Za-z])', text, re.I):
        return 'modified_or_special'
    if re.search(r'경구|복용', text) and product.get('quantity_unit') in ('정', '캡슐'):
        return 'ordinary_oral'
    return 'unknown'


def _reviewed_rules(row, records, rules):
    accepted = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if not (rule.get('reviewed') is True and rule.get('mode') == 'single'
                and rule.get('population') == 'adult' and rule.get('ingredient_code')
                and rule.get('ingredient_code') == row['ingredient_code']
                and rule.get('reviewer') and rule.get('reviewed_at') and rule.get('source_url')
                and rule.get('route') == 'oral' and rule.get('release_class') == 'ordinary_oral'):
            continue
        codes = rule.get('product_codes')
        if not isinstance(codes, list) or not codes or not set(row['products']).issubset(set(codes)):
            continue
        if any(release_class(records[code]['product']) != 'ordinary_oral' for code in row['products']):
            continue
        limit = number(rule.get('limit_mg'), '검토된 1회 기준')
        accepted.append({'kind': 'reviewed_single_ingredient_limit', 'limit_mg': str(limit),
                         'source_url': rule['source_url'], 'evidence': rule.get('evidence', ''),
                         'rule_id': rule.get('id', '')})
    return accepted


class SingleDoseService:
    def __init__(self, workflow):
        self.workflow = workflow

    def evaluate(self, submitted, rules=None):
        if not isinstance(submitted, list) or not 1 <= len(submitted) <= 30:
            raise ServiceError('공식 정보로 확인한 제품 1~30개를 목록에 추가하세요.')
        records, rows, schedules = {}, {}, []
        for item in submitted:
            if not isinstance(item, dict) or set(item) != {'approval_id'}:
                raise ServiceError('이 기능은 승인 ID만 받습니다. 정수·횟수·함량·최대량을 직접 보내지 마세요.')
            product = self.workflow._get(item['approval_id'], 'approved')
            code = str(product.get('code', ''))
            if not code or code in records or product.get('confirmed') is not True:
                raise ServiceError('공식 제품 확인 상태와 중복 품목을 확인하세요.')
            count = extract_single_count(product.get('directions_text', ''), product.get('quantity_unit'))
            ingredients = product.get('ingredients')
            if not isinstance(ingredients, list) or not ingredients:
                raise ServiceError('공식 성분 목록이 없습니다.')
            record = {'product': product, 'count': count, 'approval_id': item['approval_id']}
            records[code] = record
            schedules.append({'code': code, 'name': product['name'], 'count': copy.deepcopy(count),
                              'source_url': product.get('source', SOURCE),
                              'directions_text': document_text(product.get('directions_text', ''))})
            local_seen = set()
            for ingredient in ingredients:
                key = ingredient_key(ingredient)
                if key in local_seen:
                    raise ServiceError('공식 성분 행이 중복되어 계산할 수 없습니다.')
                local_seen.add(key)
                if not ingredient.get('name') or ingredient.get('basis_unit') != product.get('quantity_unit'):
                    raise ServiceError('공식 성분명과 함량 기준 단위를 확인하세요.')
                unit_mg = to_mg(ingredient.get('amount'), ingredient.get('unit')) / number(ingredient.get('basis_quantity'), '공식 기준 수량')
                dose = unit_mg * Decimal(count['quantity']) if count['status'] == 'known' else None
                row = rows.setdefault(key, {'ingredient': ingredient['name'],
                    'ingredient_code': str(ingredient.get('ingredient_code') or ''),
                    'matching': '공식 성분코드' if ingredient.get('ingredient_code') else '정규화 이름',
                    'products': [], 'contributions': [], 'unresolved_products': []})
                row['products'].append(code)
                row['contributions'].append({'product_code': code, 'product': product['name'],
                    'quantity': count.get('quantity'), 'quantity_unit': product['quantity_unit'],
                    'per_unit_mg': str(unit_mg), 'mg': str(dose) if dose is not None else None,
                    'count_evidence': count.get('evidence', ''), 'ingredient_evidence': ingredient.get('evidence', ''),
                    'source_url': product.get('source', SOURCE)})
                if dose is None:
                    row['unresolved_products'].append(code)
        for row in rows.values():
            row['duplicate'] = len(row['products']) > 1
            known = [Decimal(c['mg']) for c in row['contributions'] if c['mg'] is not None]
            row['known_subtotal_mg'] = str(sum(known, Decimal('0'))) if known else None
            row['total_mg'] = row['known_subtotal_mg'] if not row['unresolved_products'] else None
            row.update(criterion_status='unknown', status_label='기준 미확인', criterion_sources=[],
                       criterion_note='적용 가능한 공식 1회 비교 기준이 없습니다.')
            if row['unresolved_products']:
                row.update(status_label='복용 정수 미확인', criterion_note='일부 제품의 1회 정수가 불명확하여 전체 합계를 판정하지 않습니다.')
                continue
            criteria = _reviewed_rules(row, records, rules)
            if not criteria and not row['duplicate']:
                # 성분의 보편적 최대허용량이 아닌 해당 제품 1회 용법량과의 비교임을 구분한다.
                contribution = row['contributions'][0]
                criteria = [{'kind': 'own_product_label_amount', 'limit_mg': contribution['mg'],
                    'product_code': contribution['product_code'], 'source_url': contribution['source_url'],
                    'evidence': contribution['count_evidence']}]
            if not criteria and row['duplicate']:
                if any(release_class(records[c]['product']) != 'ordinary_oral' for c in row['products']):
                    row['criterion_note'] = '서방형·특수 제형 또는 투여 경로 미확인 제품에는 다른 제품의 1회 기준을 적용하지 않습니다.'
                    continue
                # 복합제의 1회 정수 상한을 특정 성분의 공통 최대량으로 바꾸지 않는다.
                for contribution in row['contributions']:
                    source_product = records[contribution['product_code']]['product']
                    if len(source_product['ingredients']) == 1:
                        criteria.append({'kind': 'selected_single_ingredient_label_amount',
                            'limit_mg': contribution['mg'], 'product_code': contribution['product_code'],
                            'source_url': contribution['source_url'], 'evidence': contribution['count_evidence']})
            row['criterion_sources'] = criteria
            limits = {Decimal(c['limit_mg']) for c in criteria}
            if len(limits) > 1:
                row['criterion_note'] = '적용 가능한 공식 1회 기준이 서로 달라 자동 선택하지 않습니다.'
                continue
            if len(limits) == 1:
                limit = limits.pop()
                exceeded = Decimal(row['total_mg']) > limit
                row.update(limit_mg=str(limit), criterion_status='exceeded' if exceeded else 'not_exceeded',
                           status_label='기준 초과' if exceeded else '기준 이내')
                kind = criteria[0]['kind']
                row['criterion_kind'] = kind
                row['criterion_note'] = {'own_product_label_amount': '해당 제품의 공식 1회 용법량 기준',
                    'selected_single_ingredient_label_amount': '선택한 단일성분 제품의 공식 1회 용법량을 참고 기준으로 비교',
                    'reviewed_single_ingredient_limit': '검토하여 등록한 성인 경구 1회 성분 기준'}[kind]
        output = list(rows.values())
        return {'mode': 'single_maximum_label_scenario', 'population': 'adult', 'ingredients': output,
                'schedules': schedules, 'duplicate_warning': any(r['duplicate'] for r in output),
                'has_exceeded': any(r['criterion_status'] == 'exceeded' for r in output),
                'quantity_policy': 'official_single_dose_upper_bound', 'notice': NOTICE,
                'created_at': datetime.now(timezone.utc).isoformat()}
