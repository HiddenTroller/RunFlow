import unittest
from unittest.mock import patch
import main

class DoseMergeTests(unittest.TestCase):
    def test_pending_preserves_duplicate_result(self):
        record={'detail':{'product':{'ITEM_SEQ':'123','ITEM_NAME':'미확인함량'},'ingredients_raw':[{'MTRAL_NM':'성분A'}],'warnings':[]}}
        with patch('main.WORKFLOW._get',return_value=record):
            report=main.dispatch_post('/api/check-duplicates',{'products':[{'candidate_id':'x'}]})
        self.assertEqual(report['ingredients'][0]['ingredient'],'성분A')
        self.assertFalse(report['single_dose']['complete'])
        self.assertEqual(len(report['single_dose']['excluded_products']),1)
    def test_partial_cannot_report_within(self):
        summary={'schedules':[{'count':{'status':'known'}}],'ingredients':[{'criterion_status':'not_exceeded','status_label':'기준 이내'}]}
        products=[{'code':'2','name':'미확인','amount_unconfirmed':True}]
        official={'quantity_unit':'정','ingredients':[{'unit':'mg'}]}
        with patch('main.WORKFLOW._get',return_value=official),patch('main.SINGLE_DOSE.evaluate',return_value=summary):
            result=main.single_dose_preview(products,[{'approval_id':'a'},{'candidate_id':'b'}])
        self.assertEqual(result['ingredients'][0]['criterion_status'],'unknown')
