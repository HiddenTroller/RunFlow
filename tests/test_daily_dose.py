import unittest
from daily_dose import daily_preview

def product(code,amount,directions):
 return {'code':code,'name':'약'+code,'quantity_unit':'정','directions_text':directions,'ingredients':[{'name':'성분A','ingredient_code':'M1','amount':amount,'unit':'mg','basis_quantity':'1','basis_unit':'정'}]}
RULE={'reviewed':True,'scope':'ingredient','population':'adult','min_age_years':19,'ingredient_code':'M1','mode':'day','sex':'any','limit_mg':'4000','source_url':'https://official.test','source_evidence':'TEST'}
class DailyPreviewTests(unittest.TestCase):
 def test_duplicate_daily_amounts_sum_not_limits(self):
  a=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  b=product('2','650','성인 1회 1정 1일 4회 복용한다.')
  row=daily_preview([a,b],[RULE])['ingredients'][0]
  self.assertEqual(row['total_mg'],'4100');self.assertEqual(row['limit_mg'],'4000')
  self.assertEqual(row['criterion_status'],'exceeded')
 def test_without_common_rule_no_invented_limit(self):
  p=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  row=daily_preview([p],[])['ingredients'][0]
  self.assertEqual(row['total_mg'],'1500');self.assertEqual(row['criterion_status'],'unknown');self.assertNotIn('limit_mg',row)
 def test_explicit_day_overrides_frequency(self):
  p=product('1','500','성인 1회 1정 1일 3회. 1일 최대 2정까지 복용한다.')
  self.assertEqual(daily_preview([p],[])['ingredients'][0]['total_mg'],'1000')
 def test_missing_product_never_claims_full_within(self):
  p=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  missing={'code':'2','name':'미확인','ingredients':[],'amount_unconfirmed':True}
  r=daily_preview([p,missing],[RULE]);self.assertFalse(r['complete']);self.assertEqual(r['ingredients'][0]['criterion_status'],'unknown')

class DayReferenceTests(unittest.TestCase):
 def test_selected_plain_single_product_reference(self):
  single=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  combo=product('2','300','성인 1회 1정 1일 3회 복용한다.')
  combo['ingredients'].append({'name':'다른성분','ingredient_code':'M2','amount':'10','unit':'mg','basis_quantity':'1','basis_unit':'정'})
  row=daily_preview([single,combo],[])['ingredients'][0]
  self.assertEqual(row['total_mg'],'2400');self.assertEqual(row['reference_mg'],'1500')
  self.assertEqual(row['reference_status'],'reference_exceeded');self.assertEqual(row['criterion_status'],'unknown')
  self.assertNotIn('limit_mg',row)
 def test_conflicting_product_references_stay_unknown(self):
  a=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  b=product('2','650','성인 1회 1정 1일 3회 복용한다.')
  row=daily_preview([a,b],[])['ingredients'][0]
  self.assertNotIn('reference_mg',row);self.assertEqual(row['criterion_status'],'unknown')

class IndependentDailyTests(unittest.TestCase):
 def test_fixed_daily_recommendation(self):
  from daily_dose import day_label_quantity
  p=product('1','0.5','이 약의 권장용량은 1일 1회 1정(0.5mg)이다.')
  self.assertEqual(day_label_quantity(p)['limit_quantity'],'1')
 def test_adult_explicit_maximum_before_children(self):
  from daily_dose import day_label_quantity
  p=product('1','2','성인 및 12세 이상 어린이 : 초회량은 2정, 이후 1정. 1일 최대 4정을 넘지 않도록 한다.\n9-11세 어린이: 1일 최대 3정.')
  self.assertEqual(day_label_quantity(p)['limit_quantity'],'4')
 def test_unknown_other_ingredient_does_not_block_known(self):
  a=product('1','500','성인 1회 1정 1일 3회 복용한다.')
  b=product('2','10','소아 체중에 따라 복용한다.');b['ingredients'][0]['ingredient_code']='OTHER'
  r=daily_preview([a,b],[RULE])
  self.assertFalse(r['complete'])
  self.assertEqual(r['ingredients'][0]['criterion_status'],'not_exceeded')
  self.assertEqual(r['ingredients'][1]['criterion_status'],'unknown')
