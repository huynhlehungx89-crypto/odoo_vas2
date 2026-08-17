# -*- coding: utf-8 -*-
"""Lượt 75 — rà soát khung + sáu khuyết điểm màn xem (sửa ở khung)."""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged('connecta_vas', 'connecta_vas_report_framework', 'connecta_vas_l75')
class TestVasReportFrameworkL75(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.company']._vas_w11_ensure_bctc_demo()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        cls.p01 = cls.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', cls.company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        cls.p12 = cls.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', cls.company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        cls.Snap = cls.env['vas.report.snapshot']

    def test_l75_audit_all_view_reports_use_shared_frame(self):
        """Việc 1 — mọi báo cáo XEM đi qua vas_report_client."""
        inventory = [
            ('F01 Bảng cân đối số phát sinh',
             'connecta_vas.action_vas_trial_balance_client',
             'connecta_vas.menu_vas_trial_balance'),
            ('Sổ chi tiết tài khoản',
             'connecta_vas.action_vas_account_ledger_client',
             'connecta_vas.menu_vas_account_ledger'),
            ('B01a Bảng cân đối kế toán',
             'connecta_vas.action_vas_b01a_client',
             'connecta_vas.menu_vas_b01a'),
            ('B02 Kết quả kinh doanh',
             'connecta_vas.action_vas_b02_client',
             'connecta_vas.menu_vas_b02'),
            ('B03 Lưu chuyển tiền tệ',
             'connecta_vas.action_vas_b03_client',
             'connecta_vas.menu_vas_b03'),
            ('B09 Bản thuyết minh',
             'connecta_vas.action_vas_b09_client',
             'connecta_vas.menu_vas_b09'),
        ]
        print('L75_AUDIT_HEADER name | action | frame | menu_ok')
        for name, act_xml, menu_xml in inventory:
            act = self.env.ref(act_xml)
            menu = self.env.ref(menu_xml)
            self.assertEqual(act._name, 'ir.actions.client', name)
            self.assertEqual(act.tag, 'vas_report_client', name)
            self.assertEqual(menu.action.id, act.id, name)
            print('L75_AUDIT', name, '|', act_xml, '| khung chuẩn | menu→client')

        # Bản đã lập: list là kho dữ liệu; mở bản → VIEW OWL (không form)
        for form, gen in (
            ('B01a-DNN', 'generate_b01a'),
            ('B02-DNN', 'generate_b02'),
            ('B03-DNN', 'generate_b03'),
            ('B09-DNN', 'generate_b09'),
        ):
            snap = getattr(self.Snap, gen)(
                self.company, self.p01, self.p12, hide_reversed=True,
            )
            action = snap.get_formview_action()
            self.assertEqual(action.get('type'), 'ir.actions.client', form)
            self.assertEqual(action.get('tag'), 'vas_report_client', form)
            self.assertEqual(action['context'].get('snapshot_id'), snap.id, form)
            print('L75_AUDIT open_snap', form, '→ vas_report_client')

        # Form nội bộ chỉ khi cờ rõ ràng
        snap = self.Snap.generate_b01a(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        form_act = snap.with_context(
            vas_open_snapshot_form=True,
        ).get_formview_action()
        self.assertEqual(form_act.get('type'), 'ir.actions.act_window')
        self.assertEqual(form_act.get('res_model'), 'vas.report.snapshot')

    def test_l75_six_defects_fixed_at_frame(self):
        """Sáu khuyết điểm: unlink ORM · không phân trang hợp đồng · nhãn VI ·
        không phơi trạng thái bảng · thuyết minh note_ref · cảnh báo full meta."""
        snap = self.Snap.generate_b01a(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        # (a) tầng dữ liệu
        with self.assertRaises(UserError):
            snap.line_ids[:1].unlink()
        # (b) hợp đồng đủ dòng một tờ (không cắt 40)
        data = snap.get_report_data()
        self.assertGreaterEqual(len(data['lines']), 47)
        # (c) nhãn cột tiếng Việt
        labels = [c['label'] for c in data['columns']]
        for lab in labels:
            self.assertFalse(
                lab in ('Code', 'Name', 'Line Role', 'Aggregate'),
                lab,
            )
        self.assertIn('Mã số', labels)
        self.assertIn('Chỉ tiêu', labels)
        self.assertIn('Thuyết minh', labels)
        # (d) không nhét trạng thái bảng / phân loại vào label chỉ tiêu
        for line in data['lines']:
            self.assertNotIn(' — [', line['label'])
            self.assertNotIn('Nguồn số', line['label'])
            self.assertNotIn('Phân loại điền', line['label'])
            self.assertNotIn('Trạng thái bảng', line['label'])
        # note_b09 vẫn có trong values (hợp đồng) nhưng cột đánh display=note_ref
        note_col = next(c for c in data['columns'] if c['name'] == 'note_b09')
        self.assertEqual(note_col.get('display'), 'note_ref')
        # (f) số hợp đồng là float — OWL formatCell vi-VN; kiểm không ép chuỗi en-US
        for line in data['lines']:
            for i, col in enumerate(data['columns']):
                if col.get('type') != 'monetary':
                    continue
                val = line['values'][i]
                if isinstance(val, str) and val not in ('N/A', ''):
                    self.assertNotIn(',', val, line['values'][0])
        # Cảnh báo: meta có field riêng (OWL đặt khối full-width phía trên giấy)
        self.assertIn('warning', data['meta'])

        self.Snap.generate_b02(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        b09 = self.Snap.generate_b09(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        b09_data = b09.get_report_data()
        for line in b09_data['lines']:
            self.assertNotIn(' — [', line['label'])
        code_col = next(c for c in b09_data['columns'] if c['name'] == 'code')
        self.assertEqual(code_col.get('display'), 'note_ref')
        # Khung format (PDF/XLSX cùng quy tắc OWL): không phơi .total trên mã
        printer = self.env['vas.report.print.wizard'].create({
            'data_json': '{}',
        })
        self.assertEqual(
            printer.format_print_cell('V.1.total', code_col),
            'V.1',
        )
        self.assertEqual(
            printer.format_print_cell('111', {'name': 'code', 'type': 'string'}),
            '111',
        )

    def test_l75_dummy_still_inherits_four_zones(self):
        data = self.env['vas.report.dummy.wizard'].get_report_data({})
        meta = data['meta']
        self.assertTrue(meta.get('company_name'))
        self.assertTrue(meta.get('title'))
        self.assertTrue(meta.get('form_code'))
        self.assertTrue(meta.get('period_label'))
        self.assertTrue(data['columns'])
        self.assertTrue(data['lines'])
        self.assertTrue(any(l.get('is_total') for l in data['lines']))
        self.assertEqual(
            self.env.ref('connecta_vas.action_vas_b01a_client').tag,
            'vas_report_client',
        )
        # Không menu/giao diện riêng
        self.assertFalse(self.env['ir.ui.menu'].search([
            ('name', 'ilike', 'thử khung'),
        ]))

    def test_l75_f01_numbers_stable(self):
        """F01 không vỡ: cùng khung + cột monetary căn phải."""
        act = self.env.ref('connecta_vas.action_vas_trial_balance_client')
        self.assertEqual(act.tag, 'vas_report_client')
        from odoo.addons.connecta_vas.models.vas_trial_balance import F01_COLUMNS
        self.assertEqual(F01_COLUMNS[0]['label'], 'Số hiệu TK')
        self.assertTrue(all(
            c['align'] == 'right' for c in F01_COLUMNS if c['type'] == 'monetary'
        ))
        opts = {
            'company_id': self.company.id,
            'period_from_id': self.p12.id,
            'period_to_id': self.p12.id,
            'hide_reversed': True,
        }
        data = self.env['vas.trial.balance.wizard'].get_report_data(opts)
        self.assertEqual(data['meta']['form_code'], 'F01-DNN')
        self.assertTrue(data['lines'])
        self.assertTrue(data['checks'].get('is_balanced') or 'diff_closing' in data['checks'])
