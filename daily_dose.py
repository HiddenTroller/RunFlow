"""Official adult day-label scenario; dose sums are never summed permissible limits."""
from decimal import Decimal
import re
import unicodedata
from official_text import dosage_text
from calculator import to_mg, number
from label_comparison import compare_label
from population_rules import matches
from single_dose import ingredient_key, release_class
from mfds_client import ServiceError

NOTICE='각 제품의 공식 성인 하루 표시 수량 상한을 모두 복용하는 가정입니다. 실제 섭취량·복용 권고가 아닙니다. 여러 제품의 최대량을 합친 값은 허용량이 아닙니다. 사용자 정보와 별개인 만 19세 성인 가정이며, 조건이 다른 용법은 미확인일 수 있습니다.'

def official_day_references(product):
    """Expose conditional official text without inventing or selecting a maximum."""
    source=dosage_text(product.get('directions_text',''))
    lines=[line.strip() for line in source.splitlines() if line.strip()]
    return list(dict.fromkeys(line for line in lines if re.search(r'1\s*일|하루|24\s*시간|mg/kg|mL/kg|kg당|최대|최고',line)))


def day_label_quantity(product):
    """Read an explicit adult daily cap or an unambiguous fixed daily regimen."""
    profile={'age_group':'age_based','sex':'unspecified','age_years':'19'}
    result=compare_label(dict(product,quantity='0'),profile,'day')
    if result.get('limit_quantity'):return result
    source=unicodedata.normalize('NFKC',dosage_text(product.get('directions_text','')))
    unit=product.get('quantity_unit','')
    if unit not in ('정','캡슐','포','mL'):return result
    lines=[line for line in source.splitlines() if line.strip()]
    adult=[]
    for line in lines:
        if '성인' in line:adult.append(line)
    maximum=[]
    for line in adult:
        # Restrict to the adult clause; never take a later pediatric maximum.
        section=line
        found=re.findall(r'1\s*일\s*(?:최대|최고)\s*(\d+(?:\.\d+)?)\s*'+re.escape(unit)+r'(?![A-Za-z])',section)
        maximum.extend(found)
    if len(set(maximum))==1:
        return dict(result,status='not_exceeded',limit_quantity=maximum[0],criterion_kind='explicit_adult_day_cap',source_text=source,note='공식 성인 구간의 직접 명시된 하루 상한')
    # Fixed recommendation wording e.g. 1일 1회 1정. No frequency/range guessing.
    if not re.search(r'소아|어린이|개월|kg당|/kg|초회|유지량',source):
        fixed=re.findall(r'1\s*일\s*(\d+)\s*회\s*(\d+(?:\.\d+)?)\s*'+re.escape(unit),source)
        if len(fixed)==1 and ('성인' in source or '권장용량' in source):
            quantity=Decimal(fixed[0][0])*Decimal(fixed[0][1])
            if quantity>0:return dict(result,status='not_exceeded',limit_quantity=str(quantity),criterion_kind='fixed_day_regimen',source_text=source,note='공식 권장 일일 횟수·수량의 표시량. 개인별 처방을 대체하지 않음')
    # Additional explicit daily native-unit and reversed fixed-regimen wording.
    # Do not select among multiple indications, initial/maintenance, weight or age clauses.
    if ('성인' in source or '권장용량' in source) and not re.search(r'소아|어린이|개월|초회|유지량|체중|/kg|kg당|또는|혹은',source):
        native=re.findall(r'(?:1\s*일|하루)\s*(?:총\s*|최대\s*|최고\s*)?(\d+(?:\.\d+)?)\s*'+re.escape(unit),source)
        reversed_fixed=re.findall(r'1\s*일\s*(\d+)\s*회[^.\n]{0,12}?1\s*회\s*(\d+(?:\.\d+)?)\s*'+re.escape(unit),source)
        values={Decimal(v) for v in native}
        if len(values)==1:
            q=next(iter(values))
            if q>0:return dict(result,status='not_exceeded',limit_quantity=str(q),criterion_kind='explicit_day_native_amount',source_text=source,note='공식 하루 표시 수량. 개인별 최대허용량 아님')
        if not native and len(reversed_fixed)==1:
            q=Decimal(reversed_fixed[0][0])*Decimal(reversed_fixed[0][1])
            if q>0:return dict(result,status='not_exceeded',limit_quantity=str(q),criterion_kind='fixed_day_regimen',source_text=source,note='공식 일일 횟수·1회 수량의 표시량')
    return result

def daily_preview(products,rules):
    rows={};schedules=[];excluded=[];records={p['code']:p for p in products}
    profile={'age_group':'age_based','sex':'unspecified','age_years':'19'}
    for product in products:
        label=day_label_quantity(product)
        quantity=label.get('limit_quantity') if label['status'] in ('not_exceeded','exceeded') else None
        count={'status':'known' if quantity else 'unknown','quantity':quantity,'unit':product.get('quantity_unit',''), 'evidence':label.get('source_text',''), 'reason':label.get('note',''),'official_references':official_day_references(product),'basis_kind':label.get('criterion_kind','unknown')}
        schedules.append({'code':product['code'],'name':product['name'],'count':count,'directions_text':label.get('source_text','')})
        if not product.get('ingredients') or product.get('amount_unconfirmed'):
            excluded.append({'name':product['name'],'reason':'공식 함량·단위 미확인'})
        for ingredient in product.get('ingredients',[]):
            key=ingredient_key(ingredient)
            row=rows.setdefault(key,{'ingredient':ingredient['name'],'ingredient_code':ingredient.get('ingredient_code',''),'products':[],'contributions':[],'criterion_sources':[]})
            if product['code'] in row['products']:continue
            row['products'].append(product['code']);unit=None;dose=None
            try:
                if ingredient.get('measurement_basis')=='potency' or ingredient.get('equivalence') or ingredient.get('basis_unit')!=product.get('quantity_unit'):raise ServiceError('미지원')
                unit=to_mg(ingredient.get('amount'),ingredient.get('unit'))/number(ingredient.get('basis_quantity'),'기준 수량')
                if quantity:dose=unit*Decimal(quantity)
            except (ServiceError,ValueError,TypeError):pass
            row['contributions'].append({'product_code':product['code'],'product':product['name'],'quantity_unit':product.get('quantity_unit',''),'quantity':quantity,'per_unit_mg':str(unit) if unit is not None else '미확인','mg':str(dose) if dose is not None else None})
    complete=not excluded and all(p['count']['status']=='known' for p in schedules)
    unidentified=any(not p.get('ingredients') or p.get('ingredient_identity_partial') for p in products)
    for row in rows.values():
        known=[Decimal(c['mg']) for c in row['contributions'] if c['mg'] is not None]
        row['duplicate']=len(row['products'])>1
        row['known_subtotal_mg']=str(sum(known,Decimal(0))) if known else None
        row['total_mg']=row['known_subtotal_mg'] if len(known)==len(row['contributions']) else None
        row_complete=row['total_mg'] is not None and not unidentified
        row['comparison_complete']=row_complete
        criteria=[r for r in rules if r.get('reviewed') is True and r.get('scope')=='ingredient' and r.get('mode')=='day' and r.get('ingredient_code') and r['ingredient_code']==row['ingredient_code'] and r.get('source_url') and matches(r,profile,row['products']) and r.get('limit_mg')]
        limits={number(r['limit_mg'],'하루 기준') for r in criteria}
        row.update(criterion_status='unknown',status_label='하루 기준 미확인',criterion_note='적용 가능한 성분 공통 하루 기준이 없습니다. 제품 최대량을 합쳐 허용 기준으로 사용하지 않습니다.')
        if len(limits)==1:
            limit=next(iter(limits));row['limit_mg']=str(limit)
            row['criterion_sources']=[{'evidence':r.get('source_evidence',''),'source_url':r['source_url']} for r in criteria]
            if row_complete:
                over=Decimal(row['total_mg'])>limit
                row.update(criterion_status='exceeded' if over else 'not_exceeded',status_label='하루 기준 초과' if over else '하루 기준 미초과',criterion_note='등록된 성인 성분 공통 하루 기준과 비교. 병용 가능 여부는 판단하지 않습니다.')
        # Preserve the supplied package's product-label reference comparison,
        # using day-label amounts only. This never defines a universal maximum.
        if not criteria and row['total_mg'] is not None:
            references=[]
            if not row['duplicate']:
                references=[row['contributions'][0]]
                reference_kind='own_product_day_label'
            elif all(release_class(records[code])=='ordinary_oral' for code in row['products']):
                references=[c for c in row['contributions'] if len(records[c['product_code']].get('ingredients',[]))==1 and c['mg'] is not None]
                reference_kind='selected_single_ingredient_day_label'
            values={Decimal(c['mg']) for c in references if c['mg'] is not None}
            if len(values)==1:
                reference=next(iter(values))
                row.update(reference_mg=str(reference),reference_kind=reference_kind,
                    criterion_note=' 해당 제품의 공식 하루 표시 용법량과 비교합니다. 성분 공통 최대허용량이 아닙니다.' if not row['duplicate'] else '선택한 단일성분 일반 경구 제품의 공식 하루 표시 용법량을 참고로 비교합니다. 성분 공통 최대허용량이 아닙니다.')
                row['criterion_sources']=[{'evidence':c['product']+' · 공식 하루 가정량 '+c['mg']+' mg', 'source_url':'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq='+c['product_code']} for c in references]
                if row_complete:
                    above=Decimal(row['total_mg'])>reference
                    row.update(reference_status='reference_exceeded' if above else 'reference_not_exceeded',status_label='표시 용법 참고량 초과' if above else '표시 용법 참고량 미초과')
            elif len(values)>1:
                row['criterion_note']='선택한 단일성분 제품의 공식 하루 표시 용법량이 서로 달라 참고 기준을 자동 선택하지 않습니다.'
        if not row_complete:row.update(criterion_status='unknown',status_label='전체 하루 비교 미확인',criterion_note='일부 제품의 하루 수량·함량이 미확인입니다. 확인된 부분 합계만 표시합니다.')
    return {'period':'day','schedules':schedules,'ingredients':list(rows.values()),'excluded_products':excluded,'complete':complete,'notice':NOTICE}
