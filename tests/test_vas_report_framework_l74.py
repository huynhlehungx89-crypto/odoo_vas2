# -*- coding: utf-8 -*-
"""Lượt 74 — bốn mẫu BCTC về khung OWL dùng chung + dummy + chặn xóa dòng."""
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.safe_eval import safe_eval

from odoo.addons.connecta_vas.models.vas_report_engine import FS_CLIENT_XMLIDS


@tagged('connecta_vas', 'connecta_vas_report_framework', 'connecta_vas_l74')
class TestVasReportFrameworkL74(TransactionCase):

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
        cls.Engine = cls.env['vas.report.engine']

    def _opts(self, snap=None, **extra):
        vals = {
            'company_id': self.company.id,
            'period_from_id': self.p01.id,
            'period_to_id': self.p12.id,
            'hide_reversed': True,
        }
        if snap:
            vals['snapshot_id'] = snap.id
        vals.update(extra)
        return vals

    def test_l74_menus_open_shared_client_not_odoo_list(self):
        """Sáu báo cáo chính: cùng tag vas_report_client; B01a–B09 không còn list mặc định."""
        specs = [
            ('connecta_vas.action_vas_trial_balance_client',
             'Bảng cân đối số phát sinh', 'vas.trial.balance.wizard'),
            ('connecta_vas.action_vas_account_ledger_client',
             'Sổ chi tiết tài khoản', 'vas.account.ledger.wizard'),
            ('connecta_vas.action_vas_b01a_client',
             'Bảng cân đối kế toán', 'vas.b01a.wizard'),
            ('connecta_vas.action_vas_b02_client',
             'Báo cáo kết quả kinh doanh', 'vas.b02.wizard'),
            ('connecta_vas.action_vas_b03_client',
             'Báo cáo lưu chuyển tiền tệ', 'vas.b03.wizard'),
            ('connecta_vas.action_vas_b09_client',
             'Bản thuyết minh BCTC', 'vas.b09.wizard'),
        ]
        tags = set()
        for xmlid, name, model in specs:
            act = self.env.ref(xmlid)
            self.assertEqual(act._name, 'ir.actions.client', xmlid)
            self.assertEqual(act.tag, 'vas_report_client', xmlid)
            self.assertEqual(act.name, name, xmlid)
            ctx = act.context or {}
            if isinstance(ctx, str):
                ctx = safe_eval(ctx, {'uid': 1}) or {}
            self.assertEqual(ctx.get('report_model'), model, xmlid)
            tags.add(act.tag)
        self.assertEqual(tags, {'vas_report_client'})

        menu_map = [
            ('connecta_vas.menu_vas_b01a', 'connecta_vas.action_vas_b01a_client'),
            ('connecta_vas.menu_vas_b02', 'connecta_vas.action_vas_b02_client'),
            ('connecta_vas.menu_vas_b03', 'connecta_vas.action_vas_b03_client'),
            ('connecta_vas.menu_vas_b09', 'connecta_vas.action_vas_b09_client'),
            ('connecta_vas.menu_vas_trial_balance',
             'connecta_vas.action_vas_trial_balance_client'),
            ('connecta_vas.menu_vas_account_ledger',
             'connecta_vas.action_vas_account_ledger_client'),
        ]
        for menu_xml, act_xml in menu_map:
            menu = self.env.ref(menu_xml)
            act = self.env.ref(act_xml)
            self.assertEqual(menu.action.id, act.id, menu_xml)
            self.assertEqual(menu.action._name, 'ir.actions.client', menu_xml)

    def test_l74_generate_opens_client_with_snapshot(self):
        snap = self.Snap.generate_b01a(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        wiz = self.env['vas.b01a.wizard'].create({
            'company_id': self.company.id,
            'period_from_id': self.p01.id,
            'period_to_id': self.p12.id,
            'hide_reversed': True,
        })
        action = wiz.action_generate()
        self.assertEqual(action.get('type'), 'ir.actions.client')
        self.assertEqual(action.get('tag'), 'vas_report_client')
        self.assertEqual(action.get('name'), 'Bảng cân đối kế toán')
        self.assertEqual(action['context'].get('snapshot_id'), action['context'].get('snapshot_id'))
        self.assertTrue(action['context'].get('snapshot_id'))
        opened = self.Engine.action_open_fs_client(snap)
        self.assertEqual(opened['tag'], 'vas_report_client')
        self.assertEqual(opened['context']['snapshot_id'], snap.id)
        self.assertEqual(opened['name'], 'Bảng cân đối kế toán')

    def test_l74_titles_and_b02_b03_b09_contract_shape(self):
        """Đo B02/B03/B09: hợp đồng khung + tiêu đề đúng mẫu (không dính title B01a)."""
        expected = {
            'B01a-DNN': {
                'gen': 'generate_b01a',
                'wizard': 'vas.b01a.wizard',
                'title': 'BẢNG CÂN ĐỐI KẾ TOÁN',
                'cols': ['code', 'name', 'note_b09', 'opening', 'closing'],
            },
            'B02-DNN': {
                'gen': 'generate_b02',
                'wizard': 'vas.b02.wizard',
                'title': 'BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH',
                'cols': ['code', 'name', 'note_b09', 'opening', 'closing'],
            },
            'B03-DNN': {
                'gen': 'generate_b03',
                'wizard': 'vas.b03.wizard',
                'title': 'BÁO CÁO LƯU CHUYỂN TIỀN TỆ',
                'cols': ['code', 'name', 'opening', 'closing'],
            },
            'B09-DNN': {
                'gen': 'generate_b09',
                'wizard': 'vas.b09.wizard',
                'title': 'BẢN THUYẾT MINH BÁO CÁO TÀI CHÍNH',
                'cols': [
                    'code', 'name', 'opening', 'increase', 'decrease', 'closing',
                ],
            },
        }
        for form, spec in expected.items():
            snap = getattr(self.Snap, spec['gen'])(
                self.company, self.p01, self.p12, hide_reversed=True,
            )
            data = snap.get_report_data()
            cols = [c['name'] for c in data['columns']]
            print(
                'L74_MEASURE', form,
                'title=', data['meta']['title'],
                'cols=', cols,
                'nlines=', len(data['lines']),
                'company=', data['meta']['company_name'],
                'period=', data['meta']['period_label'],
            )
            self.assertEqual(data['meta']['form_code'], form)
            self.assertEqual(data['meta']['title'], spec['title'])
            self.assertEqual(data['meta']['company_name'], self.company.name)
            self.assertTrue(data['meta']['period_label'])
            self.assertFalse(data['meta'].get('requires_account'))
            self.assertEqual(cols, spec['cols'])
            self.assertTrue(data['lines'])
            self.assertTrue(any(
                c.get('type') == 'monetary' and c.get('align') == 'right'
                for c in data['columns']
            ))
            self.assertTrue(
                any(l.get('is_total') or l.get('class') for l in data['lines']),
                form,
            )
            for line in data['lines']:
                self.assertEqual(len(line['values']), len(data['columns']), form)
            via_wiz = self.env[spec['wizard']].get_report_data(self._opts(snap))
            self.assertEqual(via_wiz['meta']['snapshot_id'], snap.id)
            self.assertTrue(via_wiz['meta'].get('from_snapshot'))

    def test_l74_line_unlink_blocked_any_path_whole_snap_ok(self):
        snap = self.Snap.generate_b01a(
            self.company, self.p01, self.p12, hide_reversed=True,
        )
        line = snap.line_ids[:1]
        self.assertTrue(line)
        with self.assertRaises(UserError) as err:
            line.unlink()
        self.assertIn('Không xóa từng dòng', str(err.exception))
        # Gọi thẳng ORM (giả lập RPC) — vẫn chặn
        with self.assertRaises(UserError):
            self.env['vas.report.snapshot.line'].browse(line.id).unlink()
        detail = line.detail_ids[:1]
        if detail:
            with self.assertRaises(UserError):
                detail.unlink()
        snap_id = snap.id
        snap.unlink()
        self.assertFalse(self.Snap.browse(snap_id).exists())

    def test_l74_xlsx_pdf_four_fs_from_saved_snapshot(self):
        generators = {
            'B01a-DNN': ('generate_b01a', 'vas.b01a.wizard'),
            'B02-DNN': ('generate_b02', 'vas.b02.wizard'),
            'B03-DNN': ('generate_b03', 'vas.b03.wizard'),
            'B09-DNN': ('generate_b09', 'vas.b09.wizard'),
        }
        for form, (gen, wizard) in generators.items():
            snap = getattr(self.Snap, gen)(
                self.company, self.p01, self.p12, hide_reversed=True,
            )
            orig = type(snap)._books_aggregate_buckets
            calls = []

            def wrapped(this, *a, **k):
                calls.append(1)
                return orig(this, *a, **k)

            type(snap)._books_aggregate_buckets = wrapped
            try:
                xlsx_act = self.env[wizard].action_export_xlsx_options(
                    self._opts(snap),
                )
                pdf_act = self.env[wizard].action_export_pdf_options(
                    self._opts(snap),
                )
            finally:
                type(snap)._books_aggregate_buckets = orig
            self.assertEqual(calls, [], 'Xuất phải đọc bản đã lưu — không gom sổ (%s)' % form)
            self.assertEqual(xlsx_act.get('type'), 'ir.actions.act_url', form)
            att_id = int(xlsx_act['url'].split('/web/content/')[1].split('?')[0])
            att = self.env['ir.attachment'].browse(att_id)
            self.assertTrue(base64.b64decode(att.datas).startswith(b'PK'), form)
            self.assertEqual(pdf_act.get('type'), 'ir.actions.report', form)
            self.assertEqual(pdf_act.get('report_name'), 'connecta_vas.report_vas_fs', form)
            ctx = pdf_act.get('context') or {}
            active_ids = ctx.get('active_ids') if isinstance(ctx, dict) else []
            self.assertTrue(active_ids, form)
            print_wiz = self.env['vas.report.print.wizard'].browse(active_ids)
            self.assertTrue(print_wiz.exists(), form)
            html, _ext = self.env['ir.actions.report']._render_qweb_html(
                'connecta_vas.action_report_vas_fs', print_wiz.ids,
            )
            text = (
                html.decode('utf-8', errors='replace')
                if isinstance(html, (bytes, bytearray)) else str(html)
            )
            data = snap.get_report_data()
            self.assertIn(self.company.name, text, form)
            self.assertIn(snap.form_code, text, form)
            self.assertIn(data['meta']['title'], text, form)
            for col in data['columns']:
                self.assertIn(col['label'], text, '%s col %s' % (form, col['name']))

    def test_l74_dummy_inherits_frame_no_menu(self):
        """Mẫu thứ bảy: cùng hợp đồng + PDF/XLSX khung, không menu, không gieo sẵn."""
        dummy = self.env['vas.report.dummy.wizard']
        data = dummy.get_report_data({})
        meta = data['meta']
        self.assertEqual(meta['form_code'], 'TEST-DUMMY')
        self.assertEqual(meta['title'], 'BÁO CÁO THỬ KHUNG')
        self.assertEqual(meta['company_name'], self.env.company.name)
        self.assertTrue(meta['period_label'])
        self.assertTrue(any(
            c.get('type') == 'monetary' and c.get('align') == 'right'
            for c in data['columns']
        ))
        self.assertTrue(any(l.get('is_total') for l in data['lines']))
        self.assertTrue(any(
            l.get('values') and l['values'][-1] == 0 for l in data['lines']
        ))
        # Cùng tag khung F01/B01a — không viết OWL riêng
        seventh = {
            'type': 'ir.actions.client',
            'tag': 'vas_report_client',
            'name': 'Báo cáo thử khung',
            'context': {
                'report_model': 'vas.report.dummy.wizard',
                'report_title': 'Báo cáo thử khung',
            },
        }
        self.assertEqual(
            seventh['tag'],
            self.env.ref('connecta_vas.action_vas_b01a_client').tag,
        )
        self.assertEqual(
            seventh['tag'],
            self.env.ref('connecta_vas.action_vas_trial_balance_client').tag,
        )
        xlsx = dummy.action_export_xlsx_options({})
        self.assertEqual(xlsx.get('type'), 'ir.actions.act_url')
        pdf = dummy.action_export_pdf_options({})
        self.assertEqual(pdf.get('type'), 'ir.actions.report')
        dummy_ids = (pdf.get('context') or {}).get('active_ids') or []
        dummy_html, _ = self.env['ir.actions.report']._render_qweb_html(
            'connecta_vas.action_report_vas_fs', dummy_ids,
        )
        dummy_text = (
            dummy_html.decode('utf-8', errors='replace')
            if isinstance(dummy_html, (bytes, bytearray)) else str(dummy_html)
        )
        self.assertIn(self.env.company.name, dummy_text)
        self.assertIn('TEST-DUMMY', dummy_text)
        self.assertIn('BÁO CÁO THỬ KHUNG', dummy_text)
        xmlids = self.env['ir.model.data'].search([
            ('module', '=', 'connecta_vas'),
            ('name', 'ilike', '%dummy%'),
            ('model', 'in', [
                'ir.ui.menu', 'ir.actions.client', 'ir.actions.act_window',
            ]),
        ])
        self.assertFalse(xmlids, xmlids.mapped('complete_name'))
        dummy_menus = self.env['ir.ui.menu'].search([
            ('name', 'ilike', 'thử khung'),
        ])
        self.assertFalse(dummy_menus)

    def test_l74_f01_contract_untouched(self):
        """F01 vẫn cùng khung + hợp đồng cũ (không vỡ số / cột)."""
        act = self.env.ref('connecta_vas.action_vas_trial_balance_client')
        self.assertEqual(act.tag, 'vas_report_client')
        ctx = act.context or {}
        if isinstance(ctx, str):
            ctx = safe_eval(ctx, {'uid': 1}) or {}
        self.assertEqual(ctx.get('report_model'), 'vas.trial.balance.wizard')
        from odoo.addons.connecta_vas.models.vas_trial_balance import F01_COLUMNS
        self.assertEqual(
            [c['name'] for c in F01_COLUMNS],
            [
                'account_code', 'account_name',
                'opening_debit', 'opening_credit',
                'ps_debit', 'ps_credit',
                'closing_debit', 'closing_credit',
            ],
        )
        self.assertTrue(all(
            c.get('align') == 'right' for c in F01_COLUMNS if c['type'] == 'monetary'
        ))
        self.assertIn('B01a-DNN', FS_CLIENT_XMLIDS)
        self.assertNotIn('F01-DNN', FS_CLIENT_XMLIDS)
