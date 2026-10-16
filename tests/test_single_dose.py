"""가상 제품·용법으로 자동 1회 계산 검증. 실제 복용 권고가 아니다."""
import copy
import unittest
from unittest.mock import patch

import main
from mfds_client import ServiceError
from single_dose import SingleDoseService, extract_single_count, document_text
from workflow import AnalysisWorkflow


def ingredient(name='가상성분A', code='component-A', amount='500', basis='1', unit='mg'):
    return {'name':name,'ingredient_code':code,'amount':amount,'unit':unit,
            'basis_quantity':basis,'basis_unit':'정','evidence':'TEST ONLY'}


def product(code='123', name='가상일반정', directions=None, ingredients=None):
    return {'code':code,'name':name,'confirmed':True,'quantity':'999999','quantity_unit':'정',
            'source':'https://example.test/fictional',
            'directions_text':directions if directions is not None else '만12세 이상 소아 및 성인: 1회 1~2정씩 4~6시간마다 필요시 복용. 1일 최대 8정.',
            'ingredients':ingredients if ingredients is not None else [ingredient()]}


class CountTests(unittest.TestCase):
    def test_attached_example_upper_bound(self):
        result=extract_single_count('만12세 이상 소아 및 성인: 1회 1~2정씩 4~6시간마다 필요시 복용. 1일 최대 4그램을 초과하여 복용하지 말 것.','정')
        self.assertEqual(result['quantity'],'2')
        self.assertEqual(result['quantity_min'],'1')

    def test_frequency_and_package_not_count(self):
        result=extract_single_count('성인: 1회 1~2정씩 1일 3~4회 복용. 1일 최대 8정. 포장 100정.','정')
        self.assertEqual(result['quantity'],'2')

    def test_exact_one_and_two(self):
        for value in ['1','2']:
            self.assertEqual(extract_single_count('성인: 1회 '+value+'정 복용.','정')['quantity'],value)

    def test_capsules(self):
        self.assertEqual(extract_single_count('성인: 1회 1~3캡슐 복용.','캡슐')['quantity'],'3')

    def test_range_variants(self):
        for separator in ['~','～','∼','〜','-','–','—']:
            with self.subTest(separator=separator):
                self.assertEqual(extract_single_count('성인: 1 회 1 '+separator+' 2 정 복용.','정')['quantity'],'2')

    def test_full_width(self):
        self.assertEqual(extract_single_count('성인: １회 １～２정 복용.','정')['quantity'],'2')

    def test_header_and_body_split(self):
        self.assertEqual(extract_single_count('만 12세 이상 소아 및 성인:\n1회 1~2정씩 1일 3-4회 복용한다.','정')['quantity'],'2')

    def test_xml_header_attribute(self):
        source='<DOC><ARTICLE title="만 12세 이상 소아 및 성인:"><PARAGRAPH>1회 1~2정씩 1일 3~4회 복용.</PARAGRAPH></ARTICLE></DOC>'
        self.assertEqual(extract_single_count(source,'정')['quantity'],'2')
        self.assertIn('성인',document_text(source))

    def test_child_section_not_selected(self):
        result=extract_single_count('성인: 1회 2정 복용.\n소아: 1회 1정 복용.','정')
        self.assertEqual(result['quantity'],'2')

    def test_child_only_unknown(self):
        for source in ['소아: 1회 1~2정 복용.','만12세 이하: 1회 3정 복용.','포장 100정. 1일 8정.','1회 1정 복용.']:
            self.assertEqual(extract_single_count(source,'정')['status'],'unknown')

    def test_missing_wrong_units_and_conditional_unknown(self):
        for source in ['',None,'성인: 1회 1캡슐 복용.','성인: 1회 0.5정 복용.','성인: 1회 -1정 복용.',
                       '성인: 1회 2~1정 복용.','성인: 1회 0~2정 복용.','성인: 1회 1정 또는 2정 복용.',
                       '성인: 체중에 따라 1회 2정 복용.','성인: 초회 1회 2정, 이후 1회 1정 복용.',
                       '성인: 1회 1정.\n성인: 1회 2정.']:
            with self.subTest(source=source):
                self.assertEqual(extract_single_count(source,'정')['status'],'unknown')

    def test_unsupported_forms(self):
        self.assertEqual(extract_single_count('성인: 1회 10mL 복용.','mL')['status'],'unknown')


class SingleDoseTests(unittest.TestCase):
    def setUp(self):
        self.flow=AnalysisWorkflow()
        self.service=SingleDoseService(self.flow)
        a=product()
        b=product('456','가상복합정','성인: 1회 1정, 1일 3회 복용.',
                  [ingredient(amount='300'),ingredient('가상성분B','component-B','50')])
        self.products=[a,b]

    def inputs(self):
        return [{'approval_id':self.flow._put('approved',copy.deepcopy(p))} for p in self.products]

    def test_automatic_max_counts_and_overlap(self):
        report=self.service.evaluate(self.inputs())
        self.assertEqual([p['count']['quantity'] for p in report['schedules']],['2','1'])
        row=report['ingredients'][0]
        self.assertEqual(row['total_mg'],'1300')
        self.assertEqual(row['limit_mg'],'1000')
        self.assertEqual(row['status_label'],'기준 초과')
        self.assertEqual(row['criterion_kind'],'selected_single_ingredient_label_amount')
        self.assertTrue(report['duplicate_warning'])

    def test_nonduplicate_is_explicit_product_label_comparison(self):
        row=self.service.evaluate(self.inputs())['ingredients'][1]
        self.assertEqual(row['total_mg'],'50')
        self.assertEqual(row['criterion_kind'],'own_product_label_amount')
        self.assertEqual(row['status_label'],'기준 이내')

    def test_day_frequency_changes_do_not_change_one_dose(self):
        before=self.service.evaluate(self.inputs())['ingredients'][0]['total_mg']
        self.products[0]['directions_text']='성인: 1회 1~2정, 1일 9회, 1일 최대 90정 복용.'
        self.products[1]['directions_text']='성인: 1회 1정, 1일 8회 복용.'
        after=self.service.evaluate(self.inputs())['ingredients'][0]['total_mg']
        self.assertEqual(before,after)

    def test_existing_manual_quantity_not_used(self):
        self.products[0]['quantity']='1'
        self.products[1]['quantity']='999999'
        self.assertEqual(self.service.evaluate(self.inputs())['ingredients'][0]['total_mg'],'1300')

    def test_basis_and_g(self):
        self.products[0]['ingredients']=[ingredient(amount='1',basis='2',unit='g')]
        self.assertEqual(self.service.evaluate(self.inputs())['ingredients'][0]['total_mg'],'1300')

    def test_unknown_count_does_not_make_partial_green(self):
        self.products[1]['directions_text']='제품 용법 확인 필요'
        row=self.service.evaluate(self.inputs())['ingredients'][0]
        self.assertIsNone(row['total_mg'])
        self.assertEqual(row['known_subtotal_mg'],'1000')
        self.assertEqual(row['status_label'],'복용 정수 미확인')
        self.assertEqual(row['criterion_status'],'unknown')

    def test_all_unknown_not_zero(self):
        for p in self.products:p['directions_text']=''
        row=self.service.evaluate(self.inputs())['ingredients'][0]
        self.assertIsNone(row['total_mg'])
        self.assertIsNone(row['known_subtotal_mg'])

    def test_combination_product_not_universal_ingredient_limit(self):
        self.products[0]['ingredients'].append(ingredient('가상성분C','component-C','20'))
        row=self.service.evaluate(self.inputs())['ingredients'][0]
        self.assertEqual(row['criterion_status'],'unknown')
        self.assertNotIn('limit_mg',row)

    def test_special_release_not_reused_as_ordinary(self):
        for name in ['가상서방정','가상이알정','가상ER정','가상장용정']:
            with self.subTest(name=name):
                self.products[1]['name']=name
                self.assertEqual(self.service.evaluate(self.inputs())['ingredients'][0]['criterion_status'],'unknown')

    def test_conflicting_single_product_benchmarks(self):
        self.products[1]['ingredients']=[ingredient(amount='300')]
        row=self.service.evaluate(self.inputs())['ingredients'][0]
        self.assertEqual(row['criterion_status'],'unknown')
        self.assertIn('서로 달라',row['criterion_note'])

    def test_identical_single_product_benchmarks(self):
        self.products[1]['ingredients']=[ingredient(amount='1000')]
        row=self.service.evaluate(self.inputs())['ingredients'][0]
        self.assertEqual(row['limit_mg'],'1000')
        self.assertEqual(row['total_mg'],'2000')

    def test_reviewed_single_rule_and_equality(self):
        self.products[0]['ingredients'].append(ingredient('가상성분C','component-C','20'))
        rule={'id':'TEST-ONLY','reviewed':True,'ingredient_code':'component-A','mode':'single',
              'population':'adult','reviewer':'TEST','reviewed_at':'2026-10-16','source_url':'https://example.test',
              'product_codes':['123','456'],'route':'oral','release_class':'ordinary_oral','limit_mg':'1300'}
        row=self.service.evaluate(self.inputs(),[rule])['ingredients'][0]
        self.assertEqual(row['status_label'],'기준 이내')
        self.assertEqual(row['criterion_kind'],'reviewed_single_ingredient_limit')
        rule['limit_mg']='1299'
        self.assertEqual(self.service.evaluate(self.inputs(),[rule])['ingredients'][0]['status_label'],'기준 초과')

    def test_daily_rule_never_converted_to_single(self):
        self.products[0]['ingredients'].append(ingredient('가상성분C','component-C','20'))
        rule={'reviewed':True,'ingredient_code':'component-A','mode':'day','population':'adult',
              'reviewer':'TEST','reviewed_at':'2026-10-16','source_url':'https://example.test',
              'product_codes':['123','456'],'route':'oral','release_class':'ordinary_oral','limit_mg':'99999'}
        self.assertEqual(self.service.evaluate(self.inputs(),[rule])['ingredients'][0]['criterion_status'],'unknown')

    def test_manual_payloads_rejected(self):
        for key in ['per_intake','times_per_day','quantity','limit_mg','ingredients']:
            values=self.inputs();values[0][key]='999'
            with self.subTest(key=key),self.assertRaises(ServiceError):self.service.evaluate(values)

    def test_duplicate_expired_and_unconfirmed(self):
        values=self.inputs()
        with self.assertRaises(ServiceError):self.service.evaluate(values+[values[0]])
        with patch('workflow.time.monotonic',return_value=10**15),self.assertRaises(ServiceError):self.service.evaluate(values)
        self.products[0]['confirmed']=False
        with self.assertRaises(ServiceError):self.service.evaluate(self.inputs())

    def test_empty_and_invalid_inputs(self):
        for value in [None,[],{},[{}],[None]]:
            with self.subTest(value=value),self.assertRaises(ServiceError):self.service.evaluate(value)

    def test_server_route(self):
        with patch('main.SINGLE_DOSE',self.service):
            result=main.dispatch_post('/api/single-dose-evaluate',{'products':self.inputs()})
        self.assertEqual(result['mode'],'single_maximum_label_scenario')


if __name__ == '__main__':
    unittest.main()
