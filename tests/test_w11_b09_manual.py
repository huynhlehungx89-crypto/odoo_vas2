# -*- coding: utf-8 -*-
"""W11 — kho người điền B09 sống sót khi lập lại; nguồn; khóa bản nộp."""
import json

from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare

from odoo.addons.connecta_vas.models.res_company import (
    W11_BCTC_EXPECT_BS,
    W11_BCTC_EXPECT_PNL60,
)
from odoo.addons.connecta_vas.models.vas_b09_entry import (
    B09_AMOUNT_CODES,
    B09_TABLE_CODES,
    B09_TEXT_CODES,
    PRIOR_PREFIX,
    SUGGESTION_PREFIX,
)
from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B09ManualEntry(TransactionCase):

    def _company_periods(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        return company, p01, p12

    def _ensure_sources(self, company, p01, p12):
        Snap = self.env['vas.report.snapshot']
        b01a = Snap._find_period_snapshot('B01a-DNN', company, p01, p12)
        b02 = Snap._find_period_snapshot('B02-DNN', company, p01, p12)
        if not b01a:
            b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        if not b02:
            b02 = Snap.generate_b02(company, p01, p12, hide_reversed=True)
        return b01a, b02

    def test_01_text_survives_regenerate(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Entry = self.env['vas.b09.entry']
        long_text = 'Dòng 1.\n\nDòng 2 dài ' + ('x' * 2000)
        Entry.get_or_create(
            company, p01, p12, 'I.3',
            text_value=long_text,
            origin='user',
            is_confirmed=True,
        )
        snap1 = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        line1 = snap1.line_ids.filtered(lambda l: l.code == 'I.3')
        self.assertEqual(line1.b09_text_value, long_text)
        self.assertEqual(line1.b09_value_source, 'user')

        snap2 = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        line2 = snap2.line_ids.filtered(lambda l: l.code == 'I.3')
        self.assertEqual(line2.b09_text_value, long_text)
        self.assertNotEqual(snap1.id, snap2.id)

    def test_02_copy_prior_year_marked(self):
        company, p01, p12 = self._company_periods()
        # Tạo FY 2025 + kỳ + entry nguồn
        fy25 = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2025-01-01'),
        ], limit=1)
        if not fy25:
            fy25 = self.env['vas.fiscalyear'].create({
                'name': 'FY2025-W11-B09',
                'company_id': company.id,
                'date_from': '2025-01-01',
                'date_to': '2025-12-31',
            })
        p25_01 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy25.id),
            ('date_start', '=', '2025-01-01'),
        ], limit=1)
        p25_12 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy25.id),
            ('date_start', '=', '2025-12-01'),
        ], limit=1)
        self.assertTrue(p25_01 and p25_12)
        self.env['vas.b09.entry'].create({
            'company_id': company.id,
            'period_from_id': p25_01.id,
            'period_to_id': p25_12.id,
            'code': 'IV.1',
            'content_kind': 'text',
            'text_value': 'Chính sách tỷ giá năm 2025',
            'origin': 'user',
            'is_confirmed': True,
        })
        # Xóa entry 2026 IV.1 nếu có (gợi ý) để chép được
        self.env['vas.b09.entry'].search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', '=', 'IV.1'),
        ]).unlink()
        created = self.env['vas.b09.entry'].copy_from_prior_year(
            company, p01, p12, only_if_empty=False,
        )
        self.assertTrue(created)
        ent = created.filtered(lambda e: e.code == 'IV.1')
        self.assertTrue(ent.is_from_prior_year)
        self.assertFalse(ent.is_confirmed)
        self.assertEqual(ent.origin, 'copied_prior')
        self.assertTrue(ent.text_value.startswith(PRIOR_PREFIX))
        self.assertIn('2025', ent.text_value)

    def test_03_three_kinds_and_table_rows(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Entry = self.env['vas.b09.entry']
        Entry.get_or_create(
            company, p01, p12, 'VIII.1',
            text_value='Thông tin khác đoạn văn',
        )
        Entry.get_or_create(
            company, p01, p12, 'V.1.equiv',
            has_opening=True, amount_opening=1000,
            has_closing=True, amount_closing=2500,
        )
        tab = Entry.get_or_create(company, p01, p12, 'V.15', content_kind='table')
        tab.write({
            'row_ids': [
                (0, 0, {'sequence': 10, 'name': 'Bên A', 'amount_closing': 10}),
                (0, 0, {'sequence': 20, 'name': 'Bên B', 'amount_closing': 20}),
                (0, 0, {'sequence': 30, 'name': 'Bên C', 'amount_closing': 30}),
            ],
        })
        # Xóa một dòng giữa — không ảnh hưởng dòng còn lại
        tab.row_ids.filtered(lambda r: r.name == 'Bên B').unlink()
        self.assertEqual(len(tab.row_ids), 2)
        self.assertEqual(set(tab.row_ids.mapped('name')), {'Bên A', 'Bên C'})

        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l for l in snap.line_ids}
        self.assertEqual(by['VIII.1'].b09_text_value, 'Thông tin khác đoạn văn')
        self.assertEqual(by['VIII.1'].b09_value_source, 'user')
        self.assertEqual(
            float_compare(by['V.1.equiv'].amount_closing, 2500, 2), 0,
        )
        self.assertEqual(by['V.1.equiv'].b09_value_source, 'user')
        rows = json.loads(by['V.15'].b09_table_json)
        self.assertEqual(len(rows), 2)
        self.assertEqual(by['V.15'].b09_value_source, 'user')

    def test_04_sources_and_pending_warn(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        # Xóa hết entry kỳ để đếm trống đầy đủ + gợi ý mới
        self.env['vas.b09.entry'].search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
        ]).unlink()
        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True, copy_prior_year=False,
        )
        by = {l.code: l for l in snap.line_ids}
        self.assertEqual(by['V.1.cash'].b09_value_source, 'machine_ledger')
        self.assertEqual(by['V.1.total'].b09_value_source, 'machine_report')
        self.assertEqual(by['II.1'].b09_value_source, 'machine_text')
        # III.1 luôn có gợi ý
        self.assertEqual(by['III.1'].b09_value_source, 'suggestion')
        self.assertTrue(by['III.1'].b09_text_value.startswith(SUGGESTION_PREFIX))
        self.assertFalse(by['III.1'].b09_is_confirmed)

        warn = snap.warning_text or ''
        self.assertIn('mục trống', warn)
        self.assertIn('chưa được kế toán xác nhận', warn)
        meta = json.loads(snap.meta_json)
        self.assertGreater(meta['b09_manual_empty_count'], 0)
        self.assertGreater(meta['b09_manual_unconfirmed_count'], 0)
        filled = sum(
            1 for c in (B09_TEXT_CODES + B09_AMOUNT_CODES + B09_TABLE_CODES)
            if by[c].b09_value_source in ('user', 'suggestion', 'copied_prior')
        )
        self.assertEqual(
            meta['b09_manual_empty_count'] + filled,
            len(B09_TEXT_CODES) + len(B09_AMOUNT_CODES) + len(B09_TABLE_CODES),
        )

    def test_05_submitted_blocks_snapshot_not_entry(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Entry = self.env['vas.b09.entry']
        ent = Entry.get_or_create(
            company, p01, p12, 'I.4',
            text_value='Trước nộp',
        )
        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        snap.action_mark_submitted()
        line = snap.line_ids.filtered(lambda l: l.code == 'I.4')
        with self.assertRaises(UserError):
            line.write({'b09_text_value': 'Sửa trên bản nộp'})
        # Kho tách vẫn sửa được cho lần lập sau
        ent.write({'text_value': 'Sau nộp — cho kỳ lập mới'})
        self.assertEqual(ent.text_value, 'Sau nộp — cho kỳ lập mới')

    def test_06_w11_b01a_b02_unchanged(self):
        company, p01, p12 = self._company_periods()
        self.env['vas.b09.entry'].get_or_create(
            company, p01, p12, 'I.5', text_value='Không ảnh hưởng B01a/B02',
        )
        b01a = self.env['vas.report.snapshot'].generate_b01a(
            company, p01, p12, hide_reversed=True,
        )
        b02 = self.env['vas.report.snapshot'].generate_b02(
            company, p01, p12, hide_reversed=True,
        )
        by1 = {l.code: l.amount_closing for l in b01a.line_ids}
        by2 = {l.code: l.amount_closing for l in b02.line_ids}
        self.assertEqual(float_compare(by1['200'], W11_BCTC_EXPECT_BS, 2), 0)
        self.assertEqual(float_compare(by1['500'], W11_BCTC_EXPECT_BS, 2), 0)
        self.assertEqual(float_compare(by2['60'], W11_BCTC_EXPECT_PNL60, 2), 0)

    def test_07_query_delta_still_zero(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Snap = self.env['vas.report.snapshot']
        # Warm-up
        Snap.generate_b09(company, p01, p12, hide_reversed=True)
        self.env.flush_all()
        with VasQueryCounter(self.env.cr) as qc1:
            Snap.generate_b09(company, p01, p12, hide_reversed=True)
            self.env.flush_all()
        n1 = qc1.count
        # Thêm nhiều chỉ tiêu probe không được — đo ổn định hai lần liên tiếp
        self.env.flush_all()
        with VasQueryCounter(self.env.cr) as qc2:
            Snap.generate_b09(company, p01, p12, hide_reversed=True)
            self.env.flush_all()
        self.assertEqual(qc2.count - n1, 0, (n1, qc2.count))

    def test_08_accountant_full_flow(self):
        """Một mạch đúng trình tự kế toán — không tách nhỏ."""
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Entry = self.env['vas.b09.entry']
        Snap = self.env['vas.report.snapshot']

        # Dọn entry các mã sẽ dùng để kịch bản sạch
        Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', 'in', ('IV.6', 'V.3a.related', 'V.15')),
        ]).unlink()

        # 1) Lập B09 lần đầu
        snap1 = Snap.generate_b09(company, p01, p12, hide_reversed=True)
        cash_before = snap1.line_ids.filtered(
            lambda l: l.code == 'V.1.cash',
        ).amount_closing

        # 2) Điền cả ba dạng
        long_iv = (
            'Nguyên tắc ghi nhận hàng tồn kho.\n'
            'Đoạn hai: giá vốn bình quân gia quyền.\n'
            'Đoạn ba: ' + ('chi tiết ' * 80)
        )
        Entry.get_or_create(
            company, p01, p12, 'IV.6',
            text_value=long_iv, origin='user', is_confirmed=True,
        )
        Entry.get_or_create(
            company, p01, p12, 'V.3a.related',
            has_opening=True, amount_opening=1_000_000,
            has_closing=True, amount_closing=3_500_000,
            origin='user', is_confirmed=True,
        )
        tab = Entry.get_or_create(company, p01, p12, 'V.15')
        tab.write({
            'row_ids': [(5, 0, 0)] + [
                (0, 0, {'sequence': 10, 'name': 'Công ty A', 'amount_closing': 100}),
                (0, 0, {'sequence': 20, 'name': 'Công ty B', 'amount_closing': 200}),
                (0, 0, {'sequence': 30, 'name': 'Công ty C', 'amount_closing': 300}),
            ],
        })
        self.assertEqual(len(tab.row_ids), 3)

        # 3) Lập lại — cả ba còn nguyên
        snap2 = Snap.generate_b09(company, p01, p12, hide_reversed=True)
        by2 = {l.code: l for l in snap2.line_ids}
        self.assertEqual(by2['IV.6'].b09_text_value, long_iv)
        self.assertEqual(
            float_compare(by2['V.3a.related'].amount_closing, 3_500_000, 2), 0,
        )
        self.assertEqual(len(json.loads(by2['V.15'].b09_table_json)), 3)
        self.assertNotEqual(snap1.id, snap2.id)

        # 4) Thêm bút toán → số máy đổi, phần người không đổi
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        move = self.env['vas.move'].create({
            'company_id': company.id,
            'journal_id': journal.id,
            'date': '2026-06-20',
            'move_kind': 'manual',
            'ref': 'W11-B09-FLOW',
            'line_ids': [
                (0, 0, {
                    'account_id': self.env.ref(
                        'connecta_vas.vas_account_tt133_111',
                    ).id,
                    'name': 'flow cash',
                    'debit': 7_000_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': self.env.ref(
                        'connecta_vas.vas_account_tt133_4111',
                    ).id,
                    'name': 'flow capital',
                    'debit': 0, 'credit': 7_000_000,
                }),
            ],
        })
        move.action_post()
        # B01a/B02 nguồn phải lập lại để B09 máy thấy số mới (B09 lấy V.1.cash từ sổ)
        Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        Snap.generate_b02(company, p01, p12, hide_reversed=True)
        snap3 = Snap.generate_b09(company, p01, p12, hide_reversed=True)
        by3 = {l.code: l for l in snap3.line_ids}
        self.assertEqual(
            float_compare(by3['V.1.cash'].amount_closing, cash_before + 7_000_000, 2),
            0,
            (cash_before, by3['V.1.cash'].amount_closing),
        )
        self.assertEqual(by3['IV.6'].b09_text_value, long_iv)
        self.assertEqual(
            float_compare(by3['V.3a.related'].amount_closing, 3_500_000, 2), 0,
        )
        self.assertEqual(len(json.loads(by3['V.15'].b09_table_json)), 3)

        # 5) Đã nộp — không sửa được bản đó
        snap3.action_mark_submitted()
        with self.assertRaises(UserError):
            by3['IV.6'].write({'b09_text_value': 'hack nộp'})
        with self.assertRaises(UserError):
            by3['V.3a.related'].write({'amount_closing': 0})

        # 6) Kỳ năm sau — chép có tiền tố; sửa năm sau không đổi năm trước
        fy27 = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2027-01-01'),
        ], limit=1)
        if not fy27:
            fy27 = self.env['vas.fiscalyear'].create({
                'name': 'FY2027-W11-B09',
                'company_id': company.id,
                'date_from': '2027-01-01',
                'date_to': '2027-12-31',
            })
        p27_01 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy27.id),
            ('date_start', '=', '2027-01-01'),
        ], limit=1)
        p27_12 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy27.id),
            ('date_start', '=', '2027-12-01'),
        ], limit=1)
        self.assertTrue(p27_01 and p27_12)
        Snap.generate_b01a(company, p27_01, p27_12, hide_reversed=True)
        Snap.generate_b02(company, p27_01, p27_12, hide_reversed=True)
        # Đảm bảo kỳ 2027 trống entry trước khi chép
        Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p27_01.id),
            ('period_to_id', '=', p27_12.id),
        ]).unlink()
        snap27 = Snap.generate_b09(
            company, p27_01, p27_12, hide_reversed=True, copy_prior_year=True,
        )
        by27 = {l.code: l for l in snap27.line_ids}
        self.assertTrue(by27['IV.6'].b09_text_value.startswith(PRIOR_PREFIX))
        self.assertIn(long_iv, by27['IV.6'].b09_text_value)
        self.assertTrue(by27['IV.6'].b09_is_from_prior)
        self.assertEqual(by27['IV.6'].b09_value_source, 'copied_prior')
        self.assertEqual(
            float_compare(by27['V.3a.related'].amount_closing, 3_500_000, 2), 0,
        )
        self.assertEqual(len(json.loads(by27['V.15'].b09_table_json)), 3)

        ent26_iv = Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', '=', 'IV.6'),
        ], limit=1)
        ent27_iv = Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p27_01.id),
            ('period_to_id', '=', p27_12.id),
            ('code', '=', 'IV.6'),
        ], limit=1)
        prior_text_26 = ent26_iv.text_value
        ent27_iv.write({'text_value': 'Sửa năm 2027 — khác hẳn'})
        self.assertEqual(ent26_iv.text_value, prior_text_26)
        self.assertEqual(ent27_iv.text_value, 'Sửa năm 2027 — khác hẳn')

        # 7) Xóa một dòng bảng (năm 2027) — hai dòng còn lại nguyên
        ent27_tab = Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p27_01.id),
            ('period_to_id', '=', p27_12.id),
            ('code', '=', 'V.15'),
        ], limit=1)
        self.assertEqual(len(ent27_tab.row_ids), 3)
        ent27_tab.row_ids.filtered(lambda r: r.name == 'Công ty B').unlink()
        self.assertEqual(len(ent27_tab.row_ids), 2)
        self.assertEqual(
            set(ent27_tab.row_ids.mapped('name')),
            {'Công ty A', 'Công ty C'},
        )
        # Kho năm trước vẫn đủ 3 dòng
        ent26_tab = Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', '=', 'V.15'),
        ], limit=1)
        self.assertEqual(len(ent26_tab.row_ids), 3)

    def test_10_vii1_survives_regenerate(self):
        company, p01, p12 = self._company_periods()
        self._ensure_sources(company, p01, p12)
        Entry = self.env['vas.b09.entry']
        text = 'Tiền phong tỏa tại NH A: 50.000.000 — lý do: ký quỹ L/C.'
        Entry.get_or_create(
            company, p01, p12, 'VII.1',
            text_value=text,
            origin='user',
            is_confirmed=True,
        )
        snap1 = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        line1 = snap1.line_ids.filtered(lambda l: l.code == 'VII.1')
        self.assertEqual(line1.b09_text_value, text)
        self.assertEqual(line1.b09_fill_kind, 'manual')
        snap2 = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        line2 = snap2.line_ids.filtered(lambda l: l.code == 'VII.1')
        self.assertEqual(line2.b09_text_value, text)

    def test_11_iv7_suggestion_follows_boc_tach_config(self):
        company, p01, p12 = self._company_periods()
        Entry = self.env['vas.b09.entry']
        company.vas_boc_tach_khau_hao_htk = False
        company.vas_khau_hao_trong_htk = 0.0
        Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', '=', 'IV.7'),
        ]).unlink()
        Entry.ensure_suggestions(company, p01, p12)
        ent = Entry.search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('code', '=', 'IV.7'),
        ], limit=1)
        self.assertTrue(ent)
        self.assertTrue(ent.text_value.startswith(SUGGESTION_PREFIX))
        self.assertFalse(ent.is_confirmed)
        self.assertIn('KHÔNG bóc tách', ent.text_value)

        company.vas_boc_tach_khau_hao_htk = True
        company.vas_khau_hao_trong_htk = 12_345_000
        Entry.ensure_suggestions(company, p01, p12)
        ent.invalidate_recordset()
        self.assertIn('BÓC TÁCH', ent.text_value)
        digits = ent.text_value.replace(',', '').replace('.', '')
        self.assertIn('12345000', digits)
