# -*- coding: utf-8 -*-
"""Chặng 4 — bảng kê hóa đơn + đối chiếu sổ / tờ khai."""
from odoo import Command
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang3 import (
    TestGtgtChang3Declaration,
)
from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang2 import (
    DATE,
    AS_OF,
)

SEP = '2026-09-10'


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c4')
class TestGtgtChang4Listing(TestGtgtChang3Declaration):
    """Bảng kê mua/bán · dòng rớt · đối chiếu · fixture Việc 6."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_chang4()

    @classmethod
    def _seed_chang4(cls):
        cls._ensure_sep_period()
        # HĐ thiếu số / thiếu ngày — kỳ 09 (không phá đối chiếu 08)
        p_miss = cls._c2_partner('NCC C4 thiếu meta', '0200444001')
        inv_no_num = cls._make_bill(
            'C4-NO-NUM', p_miss, 1_000_000.0, cls.tax_purchase[10], SEP,
        )
        inv_no_date = cls._make_bill(
            'C4-NO-DATE', p_miss, 1_000_000.0, cls.tax_purchase[10], SEP,
        )
        cls.env.cr.execute(
            "UPDATE account_move SET name = '/', ref = NULL WHERE id = %s",
            (inv_no_num.id,),
        )
        cls.env.cr.execute(
            "UPDATE account_move SET invoice_date = NULL WHERE id = %s",
            (inv_no_date.id,),
        )
        inv_no_num.invalidate_recordset()
        inv_no_date.invalidate_recordset()
        cls.seed['c4_no_num'] = inv_no_num
        cls.seed['c4_no_date'] = inv_no_date

        # Đối tác không MST — vẫn lên bảng kê
        p_novat = cls.env['res.partner'].create({
            'name': 'NCC C4 không MST',
            'vat': False,
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        inv_novat = cls._make_bill(
            'C4-NO-VAT', p_novat, 2_000_000.0, cls.tax_purchase[10], DATE,
        )
        cls._pay_bill(inv_novat, cls.bank_journal, 'c4_novat_pay')
        cls.seed['c4_no_vat'] = inv_novat

        # Dòng thuế không neo HĐ (bút toán tay / phiếu chi)
        tax10 = cls.env.ref('connecta_vas.vas_tax_10')
        journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
            ('code', 'in', ('TH', 'MH', 'NK')),
        ], limit=1)
        acc_1331 = cls._vas_acc('1331')
        acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id),
            ('code', '=', '1111'),
        ], limit=1) or cls._vas_acc('111')
        una = cls.env['vas.move'].create({
            'date': DATE,
            'journal_id': journal.id,
            'regime_id': cls.regime.id,
            'move_kind': 'manual',
            'company_id': cls.company.id,
            'currency_id': cls.vnd.id,
            'ref': 'C4-UNANCHORED-CHI',
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': acc_1331.id,
                    'name': 'Thuế không neo HĐ',
                    'debit': 50_000.0,
                    'credit': 0.0,
                    'tax_id': tax10.id,
                    'deduction_base_untaxed': 500_000.0,
                    'deductible_amount': 50_000.0,
                    'currency_id': cls.vnd.id,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': acc_111.id,
                    'name': 'Đối ứng',
                    'debit': 0.0,
                    'credit': 50_000.0,
                    'currency_id': cls.vnd.id,
                }),
            ],
        })
        una.action_post()
        cls.seed['c4_unanchored'] = una

        # Chứng từ hải quan — đã có từ C0; bổ sung số TK HQ rõ
        imp = cls.seed['import_vat']
        if not imp.declaration_number:
            imp.declaration_number = 'C4-HQ-001'

        # Doanh thu 32a / 32b / 34a để đủ bảy nhóm
        for key, tax_xml, untaxed in (
            ('c4_sale_32a', 'vas_tax_non_taxable', 100_000.0),
            ('c4_sale_32b', 'vas_tax_32b', 100_000.0),
            ('c4_sale_34a', 'vas_tax_34a', 100_000.0),
        ):
            vas_tax = cls.env.ref('connecta_vas.%s' % tax_xml)
            inv = cls.env['account.move'].create({
                'move_type': 'out_invoice',
                'company_id': cls.company.id,
                'journal_id': cls.sale_journal.id,
                'partner_id': cls.partner_customer.id,
                'invoice_date': DATE,
                'date': DATE,
                'ref': key.upper().replace('_', '-'),
                'invoice_line_ids': [Command.create({
                    'name': key,
                    'quantity': 1,
                    'price_unit': untaxed,
                    'tax_ids': [Command.clear()],
                })],
            })
            inv.action_post()
            cls.seed[key] = inv
            cls.seed['%s_vas_tax' % key] = vas_tax

    @classmethod
    def _ensure_sep_period(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', SEP),
            ('date_to', '>=', SEP),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'FY C4 2026',
                'company_id': cls.company.id,
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
            })
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', SEP),
            ('date_end', '>=', SEP),
        ], limit=1)
        if not period:
            cls.env['vas.period'].create({
                'name': '09/2026',
                'code': '2026-09',
                'date_start': '2026-09-01',
                'date_end': '2026-09-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })

    def _prep(self):
        self.company.vas_has_exempt_sales = False
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        for key in ('c4_sale_32a', 'c4_sale_32b', 'c4_sale_34a'):
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

    def _listing(self, listing_type, start='2026-08-01', end='2026-08-31'):
        rec = self.env['vas.gtgt.listing'].create({
            'company_id': self.company.id,
            'listing_type': listing_type,
            'date_start': start,
            'date_end': end,
        })
        rec.action_rebuild()
        return rec

    def _make_aug_decl(self):
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        return decl

    def test_c4_a_purchase_columns_and_footer(self):
        self._prep()
        listing = self._listing('purchase')
        details = listing.line_ids.filtered(lambda l: l.line_kind == 'detail')
        self.assertTrue(details)
        self.assertTrue(any(d.invoice_number for d in details))
        self.assertTrue(any(d.invoice_date for d in details))
        self.assertTrue(any(d.partner_name for d in details))
        self.assertGreater(listing.total_purchase_value, 0)
        self.assertGreaterEqual(listing.total_import_value, 0)
        self.assertGreater(listing.total_purchase_tax, 0)
        self.assertGreaterEqual(listing.total_deductible_tax, 0)
        self.assertGreaterEqual(listing.total_import_tax, 0)
        sum_tax = sum(listing.line_ids.filtered(
            lambda l: l.line_kind in ('detail', 'unanchored')
        ).mapped('amount_tax'))
        self.assertEqual(
            float_compare(sum_tax, listing.total_purchase_tax, 0), 0,
            'sum=%s footer=%s' % (sum_tax, listing.total_purchase_tax),
        )
        import logging
        logging.getLogger(__name__).info(
            'C4-A footer V=%s IV=%s T=%s D=%s IT=%s',
            listing.total_purchase_value, listing.total_import_value,
            listing.total_purchase_tax, listing.total_deductible_tax,
            listing.total_import_tax,
        )

    def test_c4_b_sale_seven_groups(self):
        self._prep()
        listing = self._listing('sale')
        groups = {
            l.group_code: l.amount_untaxed
            for l in listing.line_ids
            if l.line_kind == 'group_total' and l.group_code != 'unanchored'
        }
        expected = {'26', '29', '30', '32', '32a', '32b', '34a'}
        self.assertEqual(set(groups), expected, groups)
        for code in ('32a', '32b', '34a'):
            self.assertEqual(
                float_compare(groups[code], 100_000.0, 0), 0, code,
            )
        for code in expected:
            detail_sum = sum(listing.line_ids.filtered(
                lambda l, c=code: l.group_code == c and l.line_kind == 'detail'
            ).mapped('amount_untaxed'))
            self.assertEqual(
                float_compare(detail_sum, groups[code], 0), 0, code,
            )
        import logging
        logging.getLogger(__name__).info('C4-B groups=%s', groups)

    def test_c4_c_single_purpose_group(self):
        self.company.vas_has_exempt_sales = False
        self._prep()
        listing = self._listing('purchase')
        purpose_totals = listing.line_ids.filtered(
            lambda l: l.line_kind == 'group_total'
            and l.group_code in (
                'taxable_only', 'exempt_only', 'mixed', 'investment', 'unset',
            )
        )
        self.assertEqual(
            set(purpose_totals.mapped('group_code')), {'taxable_only'},
        )

    def test_c4_d_dropped_missing_number_date(self):
        self._prep()
        listing = self._listing('purchase', '2026-09-01', '2026-09-30')
        self.assertTrue(listing.drop_warning)
        self.assertGreaterEqual(len(listing.dropped_ids), 2)
        reasons = ' '.join(listing.dropped_ids.mapped('missing_reasons'))
        self.assertIn('số hóa đơn', reasons)
        self.assertIn('ngày', reasons)
        import logging
        logging.getLogger(__name__).info(
            'C4-D dropped=%s warn=%s', len(listing.dropped_ids), listing.drop_warning,
        )

    def test_c4_e_unanchored_group(self):
        self._prep()
        listing = self._listing('purchase')
        una = listing.line_ids.filtered(lambda l: l.line_kind == 'unanchored')
        self.assertTrue(una)
        self.assertTrue(any('C4-UNANCHORED' in (l.invoice_number or '') for l in una))
        tax = sum(una.mapped('amount_tax'))
        self.assertEqual(float_compare(tax, 50_000.0, 0), 0, tax)

    def test_c4_f_missing_partner_vat_warn_keep(self):
        self._prep()
        listing = self._listing('purchase')
        self.assertTrue(listing.partner_vat_warning)
        detail = listing.line_ids.filtered(
            lambda l: l.line_kind == 'detail' and 'không MST' in (l.partner_name or '')
        )
        self.assertTrue(detail)
        self.assertFalse(detail[0].partner_vat)

    def test_c4_g_import_flag(self):
        self._prep()
        listing = self._listing('purchase')
        flagged = listing.line_ids.filtered(
            lambda l: l.line_kind == 'detail' and l.is_import
        )
        customs = self.env['vas.import.vat'].search([
            ('company_id', '=', self.company.id),
            ('date', '>=', '2026-08-01'),
            ('date', '<=', '2026-08-31'),
            ('state', 'in', ('confirmed', 'paid')),
        ])
        self.assertEqual(len(flagged), len(customs))
        self.assertFalse(listing.import_flag_warning)
        import logging
        logging.getLogger(__name__).info(
            'C4-G flagged=%s customs=%s', len(flagged), len(customs),
        )

    def test_c4_h_reconcile_ledger(self):
        self._prep()
        buy = self._listing('purchase')
        buy.action_reconcile_ledger()
        rows = buy.reconcile_ids.filtered(lambda r: r.compare_kind == 'ledger')
        self.assertTrue(rows)
        bad = rows.filtered('is_mismatch')
        self.assertFalse(
            bad,
            [(r.code, r.amount_listing, r.amount_other, r.difference) for r in bad],
        )
        sale = self._listing('sale')
        sale.action_reconcile_ledger()
        srows = sale.reconcile_ids.filtered(lambda r: r.compare_kind == 'ledger')
        sbad = srows.filtered('is_mismatch')
        self.assertFalse(
            sbad,
            [(r.code, r.amount_listing, r.amount_other, r.difference) for r in sbad],
        )
        import logging
        logging.getLogger(__name__).info(
            'C4-H buy=%s sale=%s',
            [(r.code, r.amount_listing, r.amount_other) for r in rows],
            [(r.code, r.amount_listing, r.amount_other) for r in srows],
        )

    def test_c4_i_reconcile_declaration(self):
        self._prep()
        decl = self._make_aug_decl()
        buy = self._listing('purchase')
        buy.declaration_id = decl
        buy.action_reconcile_declaration()
        codes = ('23', '23a', '24', '24a', '25')
        brows = {
            r.code: r
            for r in buy.reconcile_ids
            if r.compare_kind == 'declaration'
        }
        for c in codes:
            self.assertIn(c, brows)
            self.assertFalse(
                brows[c].is_mismatch,
                '%s list=%s decl=%s diff=%s' % (
                    c, brows[c].amount_listing, brows[c].amount_other,
                    brows[c].difference,
                ),
            )
        sale = self._listing('sale')
        sale.declaration_id = decl
        sale.action_reconcile_declaration()
        scodes = (
            '26', '29', '30', '31', '32', '32a', '32b', '33', '34', '34a', '35',
        )
        srows = {
            r.code: r
            for r in sale.reconcile_ids
            if r.compare_kind == 'declaration'
        }
        for c in scodes:
            self.assertIn(c, srows)
            self.assertFalse(
                srows[c].is_mismatch,
                '%s list=%s decl=%s diff=%s' % (
                    c, srows[c].amount_listing, srows[c].amount_other,
                    srows[c].difference,
                ),
            )
        import logging
        logging.getLogger(__name__).info(
            'C4-I buy=%s sale=%s',
            {c: (brows[c].amount_listing, brows[c].amount_other) for c in codes},
            {c: (srows[c].amount_listing, srows[c].amount_other) for c in scodes},
        )

    def test_c4_j_mismatch_points_to_group(self):
        self._prep()
        buy = self._listing('purchase')
        buy.action_reconcile_ledger()
        detail = buy.line_ids.filtered(lambda l: l.line_kind == 'detail')[:1]
        self.assertTrue(detail)
        detail.amount_tax += 1_000.0
        buy._rebuild_reconcile_ledger()
        bad = buy.reconcile_ids.filtered(
            lambda r: r.compare_kind == 'ledger' and r.is_mismatch
        )
        self.assertTrue(bad)
        self.assertTrue(any(abs(r.difference) >= 1000 for r in bad))

        decl = self._make_aug_decl()
        buy.declaration_id = decl
        buy.total_purchase_tax += 2_000.0
        buy._rebuild_reconcile_declaration()
        dbad = buy.reconcile_ids.filtered(
            lambda r: r.compare_kind == 'declaration'
            and r.code == '24' and r.is_mismatch
        )
        self.assertTrue(dbad)
        self.assertEqual(
            float_compare(abs(dbad[0].difference), 2_000.0, 0), 0,
        )
        import logging
        logging.getLogger(__name__).info(
            'C4-J ledger_bad=%s decl_24_diff=%s',
            [(r.code, r.difference) for r in bad],
            dbad[0].difference,
        )

    def test_c4_k_open_source(self):
        self._prep()
        listing = self._listing('purchase')
        line = listing.line_ids.filtered(
            lambda l: l.line_kind == 'detail' and l.source_model == 'account.move'
        )[:1]
        self.assertTrue(line)
        action = line.action_open_source()
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['res_id'], line.source_res_id)
