# -*- coding: utf-8 -*-
"""B03-4 — cột Thuyết minh B01a/B02 trỏ mã mục B09 ổn định."""
from odoo.tests import tagged, TransactionCase

from odoo.addons.connecta_vas.tests.test_w11_b09 import B09_FROM_B01A, B09_FROM_B02

# B09_FROM_* : mã B09 → mã nguồn B01a/B02. Đảo lại cho cột thuyết minh.
NOTE_B01A = {src: b09 for b09, src in B09_FROM_B01A.items()}
NOTE_B02 = {src: b09 for b09, src in B09_FROM_B02.items()}


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11NoteB09Column(TransactionCase):

    def test_01_seed_note_b09_codes_match_mapping(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        for form, mapping in (
            ('B01a-DNN', NOTE_B01A),
            ('B02-DNN', NOTE_B02),
        ):
            lines = self.env['vas.report.line'].search([
                ('form_code', '=', form),
                ('regime_id', '=', regime.id),
                ('active', '=', True),
            ])
            by = {l.code: l for l in lines}
            for code, note in mapping.items():
                self.assertEqual(
                    by[code].note_b09_code, note,
                    '%s mã %s' % (form, code),
                )
            if form == 'B01a-DNN':
                self.assertFalse(by['200'].note_b09_code)
                self.assertFalse(by['500'].note_b09_code)

    def test_02_get_report_data_shows_note_column(self):
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
        Snap = self.env['vas.report.snapshot']
        b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        b02 = Snap.generate_b02(company, p01, p12, hide_reversed=True)
        for snap, expect_map in ((b01a, NOTE_B01A), (b02, NOTE_B02)):
            data = snap.get_report_data()
            col_names = [c['name'] for c in data['columns']]
            self.assertIn('note_b09', col_names, snap.form_code)
            self.assertEqual(col_names[2], 'note_b09')
            by = {l['values'][0]: l['values'][2] for l in data['lines']}
            for code, note in expect_map.items():
                self.assertEqual(
                    by.get(code), note, '%s/%s' % (snap.form_code, code),
                )
            for sl in snap.line_ids.filtered(lambda l: l.code in expect_map):
                self.assertEqual(sl.note_b09_code, expect_map[sl.code])

    def test_03_rename_reorder_b09_does_not_break_note(self):
        """Đổi tên / thứ tự mục B09 không làm gãy cột thuyết minh (trỏ theo mã)."""
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        b01_110 = self.env['vas.report.line'].search([
            ('form_code', '=', 'B01a-DNN'),
            ('regime_id', '=', regime.id),
            ('code', '=', '110'),
        ], limit=1)
        self.assertEqual(b01_110.note_b09_code, 'V.1.total')
        b09 = self.env['vas.report.line'].search([
            ('form_code', '=', 'B09-DNN'),
            ('regime_id', '=', regime.id),
            ('code', '=', 'V.1.total'),
        ], limit=1)
        old_name = b09.name
        old_seq = b09.sequence
        b09.write({
            'name': 'ĐỔI TÊN THỬ — vẫn cùng mã V.1.total',
            'sequence': old_seq + 9999,
        })
        self.assertEqual(b01_110.note_b09_code, 'V.1.total')
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
        snap = self.env['vas.report.snapshot'].generate_b01a(
            company, p01, p12, hide_reversed=True,
        )
        data = snap.get_report_data()
        by = {l['values'][0]: l['values'][2] for l in data['lines']}
        self.assertEqual(by['110'], 'V.1.total')
        b09.write({'name': old_name, 'sequence': old_seq})
