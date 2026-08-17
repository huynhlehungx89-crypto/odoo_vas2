# -*- coding: utf-8 -*-
"""Chặng 5 — giảm thuế GTGT theo NQ 204 / NĐ 174."""
from odoo import Command
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang4 import (
    TestGtgtChang4Listing,
)
from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang2 import (
    DATE,
    AS_OF,
)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c5')
class TestGtgtChang5Nq204(TestGtgtChang4Listing):
    """Danh mục dữ liệu · [32]/[33] · phụ lục · cảnh báo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_chang5()

    @classmethod
    def _seed_chang5(cls):
        # SP được giảm — mã VSIC không thuộc danh mục loại trừ
        cls.prod_ok = cls.env['product.product'].create({
            'name': 'DV C5 được giảm 8%',
            'default_code': 'C5-OK-8',
            'type': 'service',
            'categ_id': cls.cat.id,
            'list_price': 5_000_000.0,
            'sale_ok': True,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'vas_vsic_code': '47',
        })
        inv_ok = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.sale_journal.id,
            'partner_id': cls.partner_customer.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C5-OK-8',
            'invoice_line_ids': [Command.create({
                'product_id': cls.prod_ok.id,
                'name': cls.prod_ok.name,
                'quantity': 1,
                'price_unit': 5_000_000.0,
                'tax_ids': [Command.set(cls.tax_sale[8].ids)],
            })],
        })
        inv_ok.action_post()
        cls.seed['c5_ok_8'] = inv_ok

        # SP không được giảm — VSIC viễn thông 61
        cls.prod_excl = cls.env['product.product'].create({
            'name': 'DV C5 viễn thông (không giảm)',
            'default_code': 'C5-EXCL-61',
            'type': 'service',
            'categ_id': cls.cat.id,
            'list_price': 2_000_000.0,
            'sale_ok': True,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'vas_vsic_code': '61',
        })
        inv_excl = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.sale_journal.id,
            'partner_id': cls.partner_customer.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C5-EXCL-8',
            'invoice_line_ids': [Command.create({
                'product_id': cls.prod_excl.id,
                'name': cls.prod_excl.name,
                'quantity': 1,
                'price_unit': 2_000_000.0,
                'tax_ids': [Command.set(cls.tax_sale[8].ids)],
            })],
        })
        inv_excl.action_post()
        cls.seed['c5_excl_8'] = inv_excl

        # SP chưa có chiều nhận diện + 8%
        cls.prod_undet = cls.env['product.product'].create({
            'name': 'DV C5 chưa xác định',
            'default_code': 'C5-UNDET',
            'type': 'service',
            'categ_id': cls.cat.id,
            'list_price': 1_000_000.0,
            'sale_ok': True,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })
        inv_undet = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.sale_journal.id,
            'partner_id': cls.partner_customer.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C5-UNDET-8',
            'invoice_line_ids': [Command.create({
                'product_id': cls.prod_undet.id,
                'name': cls.prod_undet.name,
                'quantity': 1,
                'price_unit': 1_000_000.0,
                'tax_ids': [Command.set(cls.tax_sale[8].ids)],
            })],
        })
        inv_undet.action_post()
        cls.seed['c5_undet_8'] = inv_undet

        # Gán VSIC cho sale_8 cũ (C0) nếu trống — để không phá ca undetermined C5
        # (giữ sale_8 không mã → undetermined chung kỳ)

    def _prep_c5(self):
        self.company.vas_has_exempt_sales = False
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        # Gắn tag 32a/32b/34a như C4
        for key in ('c4_sale_32a', 'c4_sale_32b', 'c4_sale_34a'):
            if key not in self.seed:
                continue
            inv = self.seed[key]
            vas_tax = self.seed['%s_vas_tax' % key]
            moves = self._vas_for_invoice(inv)
            rev = moves.mapped('line_ids').filtered(
                lambda l: (l.account_id.code or '').startswith('511')
            )
            rev.with_context(
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({'tax_id': vas_tax.id, 'tax_status': 'resolved'})

    def _amt(self, decl, code):
        line = decl.line_ids.filtered(lambda l: l.code == code)[:1]
        self.assertTrue(line, 'thiếu %s' % code)
        return line.amount

    def test_c5_a_source_pages(self):
        """A — khóa đọc nguồn (số trang ghi trong docstring / báo cáo)."""
        # Kiểm dữ liệu hiệu lực khớp NQ 204 tr.1 / NĐ 174 tr.2
        tax8 = self.env.ref('connecta_vas.vas_tax_8')
        self.assertEqual(str(tax8.date_start), '2025-07-01')
        self.assertEqual(str(tax8.date_end), '2026-12-31')
        self.assertEqual(tax8.rate, 8.0)
        excl = self.env['vas.gtgt.reduction.exclusion'].search([], limit=1)
        self.assertTrue(excl)
        self.assertEqual(str(excl.date_start), '2025-07-01')
        import logging
        logging.getLogger(__name__).info(
            'C5-A rate=8 force=%s→%s excl_n=%s',
            tax8.date_start, tax8.date_end,
            self.env['vas.gtgt.reduction.exclusion'].search_count([]),
        )

    def test_c5_b_exclusion_is_data(self):
        """B — đổi dữ liệu danh mục → kết quả kiểm đổi, không sửa mã."""
        Excl = self.env['vas.gtgt.reduction.exclusion']
        # Tạm thêm mã 47 vào danh mục loại trừ
        row = Excl.create({
            'code': '47',
            'name': 'TEST tạm loại trừ mã 47',
            'code_kind': 'vsic',
            'annex': 'I',
            'date_start': '2025-07-01',
            'date_end': '2026-12-31',
        })
        status, hit = Excl.match_product(self.prod_ok, DATE)
        self.assertEqual(status, 'excluded')
        self.assertEqual(hit.code, '47')
        row.unlink()
        status2, _ = Excl.match_product(self.prod_ok, DATE)
        self.assertEqual(status2, 'allowed')

    def test_c5_c_d_e_ok8_into_32_33_annex_34(self):
        self._prep_c5()
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        a32 = self._amt(decl, '32')
        a33 = self._amt(decl, '33')
        a34 = self._amt(decl, '34')
        a26 = self._amt(decl, '26')
        a27 = self._amt(decl, '27')
        a34a = self._amt(decl, '34a')
        # Doanh thu 8% được giảm (5tr) + sale_8 C0 (1tr) + excl/undet vẫn trên sổ 8% → [32]
        self.assertGreaterEqual(a32, 5_000_000.0)
        self.assertGreaterEqual(a33, 400_000.0)  # 5tr×8% = 400k tối thiểu từ HĐ OK
        self.assertEqual(
            float_compare(a34, a26 + a27 + a34a, 0), 0,
            '34=%s 26=%s 27=%s 34a=%s' % (a34, a26, a27, a34a),
        )
        self.assertTrue(decl.show_reduction_annex)
        annex = decl.reduction_annex_id
        self.assertTrue(annex)
        self.assertEqual(float_compare(annex.amount_07, 5_000_000.0, 0), 0, annex.amount_07)
        self.assertEqual(float_compare(annex.amount_08, 400_000.0, 0), 0, annex.amount_08)
        import logging
        logging.getLogger(__name__).info(
            'C5-CDE 32=%s 33=%s 34=%s(=26=%s+27=%s+34a=%s) annex07=%s annex08=%s',
            a32, a33, a34, a26, a27, a34a, annex.amount_07, annex.amount_08,
        )

    def test_c5_f_excluded_warns(self):
        self._prep_c5()
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        warns = self.env['vas.gtgt.reduction.warning'].search([
            ('declaration_id', '=', decl.id),
            ('warning_kind', '=', 'excluded'),
        ])
        self.assertTrue(warns)
        self.assertTrue(any('viễn thông' in (w.product_name or '').lower()
                            or '61' in (w.message or '') for w in warns))
        import logging
        logging.getLogger(__name__).info('C5-F %s', warns[0].message)

    def test_c5_g_out_of_force(self):
        self._prep_c5()
        # HĐ 8% 01/2027 đã có từ C0
        decl = self._make_decl(self.company, 2027, month=1)
        decl.action_recompute_amounts()
        warns = self.env['vas.gtgt.reduction.warning'].search([
            ('declaration_id', '=', decl.id),
            ('warning_kind', '=', 'out_of_force'),
        ])
        self.assertTrue(warns)
        import logging
        logging.getLogger(__name__).info('C5-G n=%s %s', len(warns), warns[0].message)

    def test_c5_h_undetermined(self):
        self._prep_c5()
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        warns = self.env['vas.gtgt.reduction.warning'].search([
            ('declaration_id', '=', decl.id),
            ('warning_kind', '=', 'undetermined'),
        ])
        self.assertTrue(warns)
        self.assertTrue(any('CHƯA XÁC ĐỊNH' in (w.message or '') for w in warns))
        # Không vào phụ lục như hàng được giảm
        annex = decl.reduction_annex_id
        if annex:
            names = annex.line_ids.mapped('product_name')
            self.assertFalse(any('chưa xác định' in (n or '').lower() for n in names))

    def test_c5_i_no_annex_when_no_eligible(self):
        self._prep_c5()
        decl = self._make_decl(self.company, 2026, month=5)
        decl.action_recompute_amounts()
        self.assertFalse(decl.show_reduction_annex)
        self.assertFalse(decl.reduction_annex_ids)

    def test_c5_j_listing_matches_declaration(self):
        self._prep_c5()
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        listing = self.env['vas.gtgt.listing'].create({
            'company_id': self.company.id,
            'listing_type': 'sale',
            'date_start': '2026-08-01',
            'date_end': '2026-08-31',
            'declaration_id': decl.id,
        })
        listing.action_rebuild()
        listing.action_reconcile_declaration()
        rows = {
            r.code: r for r in listing.reconcile_ids
            if r.compare_kind == 'declaration'
        }
        for code in ('32', '33', '34', '35'):
            self.assertIn(code, rows)
            self.assertFalse(
                rows[code].is_mismatch,
                '%s list=%s decl=%s' % (
                    code, rows[code].amount_listing, rows[code].amount_other,
                ),
            )
        import logging
        logging.getLogger(__name__).info(
            'C5-J %s',
            {c: (rows[c].amount_listing, rows[c].amount_other)
             for c in ('32', '33', '34', '35')},
        )
