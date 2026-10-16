import unittest
from daily_dose import day_label_quantity,official_day_references
class BroaderReferencesTests(unittest.TestCase):
 def test_native_daily_amount(self):
  p={'name':'가상약','code':'1','quantity_unit':'정','directions_text':'성인 권장용량은 1일 2정이다.'}
  self.assertEqual(day_label_quantity(p)['limit_quantity'],'2')
 def test_weight_reference_visible_not_selected(self):
  p={'name':'가상소아약','code':'1','quantity_unit':'mL','directions_text':'소아 1회 0.5mL/kg, 1일 최대 4회. 체중에 따라 복용한다.'}
  self.assertTrue(official_day_references(p))
  self.assertIsNone(day_label_quantity(p).get('limit_quantity'))
 def test_indication_references_not_merged(self):
  p={'directions_text':'관절염: 성인 1일 최대 3200mg.\n편두통: 성인 24시간 동안 2캡슐을 초과하지 않는다.'}
  refs=official_day_references(p);self.assertEqual(len(refs),2);self.assertIn('관절염',refs[0]);self.assertIn('편두통',refs[1])
