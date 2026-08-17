# -*- coding: utf-8 -*-
"""Chặng 7 — phương pháp trực tiếp mẫu 03/04."""
import logging
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang3 import (
    TestGtgtChang3Declaration,
)
from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang2 import AS_OF

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c7')
class TestGtgtChang7Direct(TestGtgtChang3Declaration):
    """Nhóm ngành · PP thuế · 03/04 · backfill."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_03 = cls.env.ref('connecta_vas.vas_gtgt_form_03')
        cls.form_04 = cls.env.ref('connecta_vas.vas_gtgt_form_04')
        cls.ind_dist = cls.env.ref('connecta_vas.vas_gtgt_ind_dist')
        cls.ind_svc = cls.env.ref('connecta_vas.vas_gtgt_ind_svc')
        cls.ind_mfg = cls.env.ref('connecta_vas.vas_gtgt_ind_mfg')
        cls.ind_other = cls.env.ref('connecta_vas.vas_gtgt_ind_other')
        cls.ind_gold = cls.env.ref('connecta_vas.vas_gtgt_ind_gold')
        cls._seed_chang7()

    @classmethod
    def _seed_chang7(cls):
        Method = cls.env['vas.gtgt.tax.method']
        Reg = cls.env['vas.gtgt.registration']

        def _ensure_co(name):
            co = cls.env['res.company'].create({
                'name': name,
                'currency_id': cls.vnd.id,
            })
            Chart = cls.env['account.chart.template']
            for tpl in ('vn', 'generic_coa'):
                try:
                    Chart.try_loading(tpl, co, install_demo=False)
                    break
                except Exception:
                    continue
            co.vas_regime_id = cls.regime
            co.vas_start_date = '2000-01-01'
            co.currency_id = cls.vnd  # chart có thể đổi sang USD
            cls.env['vas.journal']._ensure_journals_for_company(co)
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2026',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': co.id,
            })
            fy.action_generate_periods()
            tax10 = cls.env['account.tax'].with_company(co).search([
                ('company_id', '=', co.id),
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 10.0),
                ('amount_type', '=', 'percent'),
            ], limit=1)
            if not tax10:
                tax10 = cls.env['account.tax'].with_company(co).create({
                    'name': 'C7 GTGT 10%% %s' % name[:8],
                    'amount': 10.0,
                    'amount_type': 'percent',
                    'type_tax_use': 'sale',
                    'company_id': co.id,
                    'country_id': cls.tax_sale[10].country_id.id,
                    'tax_group_id': cls.tax_sale[10].tax_group_id.id,
                    'invoice_repartition_line_ids': [
                        Command.create({'repartition_type': 'base', 'factor': 100}),
                        Command.create({'repartition_type': 'tax', 'factor': 100}),
                    ],
                    'refund_repartition_line_ids': [
                        Command.create({'repartition_type': 'base', 'factor': 100}),
                        Command.create({'repartition_type': 'tax', 'factor': 100}),
                    ],
                })
            sj = cls.env['account.journal'].with_company(co).search([
                ('company_id', '=', co.id), ('type', '=', 'sale'),
            ], limit=1)
            if not sj:
                sj = cls.env['account.journal'].create({
                    'name': 'Sale %s' % name[:12],
                    'code': 'S%s' % (co.id % 1000),
                    'type': 'sale',
                    'company_id': co.id,
                })
            return co, tax10, sj

        def _prod(code, name, industry, price, company):
            prod = cls.env['product.product'].with_company(company).create({
                'name': name,
                'default_code': code,
                'type': 'service',
                'categ_id': cls.cat.id,
                'list_price': price,
                'sale_ok': True,
                'uom_id': cls.env.ref('uom.product_uom_unit').id,
                'vas_gtgt_direct_industry_id': industry.id if industry else False,
            })
            # Gán TK doanh thu công ty nếu còn trống
            income = cls.env['account.account'].with_company(company).search([
                ('company_ids', 'in', company.id),
                ('account_type', '=', 'income'),
            ], limit=1)
            if income and not prod.property_account_income_id:
                prod.with_company(company).property_account_income_id = income
            return prod

        # DN trực tiếp — đủ 4 nhóm
        cls.company_d, cls.tax10_d, cls.sale_j_d = _ensure_co('C7 Direct Co')
        Method.create({
            'company_id': cls.company_d.id,
            'method': 'direct',
            'date_start': '2026-01-01',
        })
        Reg.create({
            'company_id': cls.company_d.id,
            'form_type_id': cls.form_04.id,
            'period_kind': 'month',
        })
        cls.partner_d = cls.env['res.partner'].create({
            'name': 'KH C7 Direct', 'company_id': cls.company_d.id,
            'customer_rank': 1,
        })

        cls.prod_dist = _prod('C7-DIST', 'HH phân phối', cls.ind_dist, 10_000_000, cls.company_d)
        cls.prod_svc = _prod('C7-SVC', 'DV không bao thầu', cls.ind_svc, 8_000_000, cls.company_d)
        cls.prod_mfg = _prod('C7-MFG', 'SX gắn HH', cls.ind_mfg, 6_000_000, cls.company_d)
        cls.prod_other = _prod('C7-OTH', 'KD khác', cls.ind_other, 4_000_000, cls.company_d)
        cls.prod_undet = _prod('C7-UNDET', 'Chưa nhóm ngành', False, 1_000_000, cls.company_d)

        lines = []
        for prod, price in (
            (cls.prod_dist, 10_000_000),
            (cls.prod_svc, 8_000_000),
            (cls.prod_mfg, 6_000_000),
            (cls.prod_other, 4_000_000),
        ):
            lines.append(Command.create({
                'product_id': prod.id,
                'name': prod.name,
                'quantity': 1,
                'price_unit': price,
                'tax_ids': [Command.set(cls.tax10_d.ids)],
            }))
        inv = cls.env['account.move'].with_company(cls.company_d).create({
            'move_type': 'out_invoice',
            'company_id': cls.company_d.id,
            'journal_id': cls.sale_j_d.id,
            'partner_id': cls.partner_d.id,
            'invoice_date': '2026-08-15',
            'date': '2026-08-15',
            'ref': 'C7-4GRP-AUG',
            'invoice_line_ids': lines,
        })
        inv.action_post()
        cls.seed['c7_4grp'] = inv

        inv_u = cls.env['account.move'].with_company(cls.company_d).create({
            'move_type': 'out_invoice',
            'company_id': cls.company_d.id,
            'journal_id': cls.sale_j_d.id,
            'partner_id': cls.partner_d.id,
            'invoice_date': '2026-09-10',
            'date': '2026-09-10',
            'ref': 'C7-UNDET',
            'invoice_line_ids': [Command.create({
                'product_id': cls.prod_undet.id,
                'name': cls.prod_undet.name,
                'quantity': 1,
                'price_unit': 1_000_000,
                'tax_ids': [Command.set(cls.tax10_d.ids)],
            })],
        })
        inv_u.action_post()
        cls.seed['c7_undet'] = inv_u

        # DN vàng — mẫu 03
        cls.company_g, cls.tax10_g, cls.sale_j_g = _ensure_co('C7 Gold Co')
        Method.create({
            'company_id': cls.company_g.id,
            'method': 'direct',
            'date_start': '2026-01-01',
        })
        Reg.create({
            'company_id': cls.company_g.id,
            'form_type_id': cls.form_03.id,
            'period_kind': 'month',
        })
        cls.partner_g = cls.env['res.partner'].create({
            'name': 'KH C7 Gold', 'company_id': cls.company_g.id,
            'customer_rank': 1,
        })
        cls.prod_gold = _prod(
            'C7-GOLD', 'Vàng trang sức', cls.ind_gold, 50_000_000, cls.company_g,
        )
        inv_g = cls.env['account.move'].with_company(cls.company_g).create({
            'move_type': 'out_invoice',
            'company_id': cls.company_g.id,
            'journal_id': cls.sale_j_g.id,
            'partner_id': cls.partner_g.id,
            'invoice_date': '2026-08-20',
            'date': '2026-08-20',
            'ref': 'C7-GOLD-SALE',
            'invoice_line_ids': [Command.create({
                'product_id': cls.prod_gold.id,
                'name': cls.prod_gold.name,
                'quantity': 1,
                'price_unit': 50_000_000,
                'tax_ids': [Command.set(cls.tax10_g.ids)],
            })],
        })
        inv_g.action_post()
        cls.seed['c7_gold_sale'] = inv_g

        # DN đổi PP giữa năm
        cls.company_sw, cls.tax10_sw, cls.sale_j_sw = _ensure_co('C7 Switch Co')
        Method.create({
            'company_id': cls.company_sw.id,
            'method': 'deduction',
            'date_start': '2026-01-01',
            'date_end': '2026-08-31',
        })
        Method.create({
            'company_id': cls.company_sw.id,
            'method': 'direct',
            'date_start': '2026-09-01',
        })
        Reg.create({
            'company_id': cls.company_sw.id,
            'form_type_id': cls.form_01.id,
            'period_kind': 'month',
            'date_start': '2026-01-01',
            'date_end': '2026-08-31',
        })
        Reg.create({
            'company_id': cls.company_sw.id,
            'form_type_id': cls.form_04.id,
            'period_kind': 'month',
            'date_start': '2026-09-01',
        })

    def _sync_co(self, company):
        return self.env['vas.sync'].sync_company(
            company, date_from='2026-01-01', date_to='2026-12-31',
        )

    def _make_direct_decl(self, company, form, year, month):
        start, end = self.env['vas.gtgt.declaration']._period_bounds(
            'month', year, month=month,
        )
        ver = self.env['vas.gtgt.form.version'].find_for_period_start(form, start)
        return self.env['vas.gtgt.declaration'].create({
            'company_id': company.id,
            'form_type_id': form.id,
            'form_version_id': ver.id,
            'period_kind': 'month',
            'year': year,
            'month': month,
            'date_start': start,
            'date_end': end,
            'activity_id': self.act_sxkd.id,
            'declaration_round': 0,
        })

    def test_c7_a_source_rates(self):
        """Ca A — bốn nhóm + tỷ lệ từ dữ liệu / nguồn."""
        Ind = self.env['vas.gtgt.direct.industry']
        rows = Ind.search([('is_gold', '=', False)], order='sequence')
        self.assertEqual(len(rows), 4)
        rates = {r.code: r.rate_percent for r in rows}
        self.assertEqual(rates['DIST'], 1.0)
        self.assertEqual(rates['SVC'], 5.0)
        self.assertEqual(rates['MFG'], 3.0)
        self.assertEqual(rates['OTHER'], 2.0)
        self.assertTrue(self.form_03.exists())
        self.assertTrue(self.form_04.exists())

    def test_c7_b_rate_is_data(self):
        """Ca B — đổi tỷ lệ dữ liệu → thuế đổi, không sửa mã."""
        self._sync_co(self.company_d)
        decl = self._make_direct_decl(self.company_d, self.form_04, 2026, 8)
        decl.action_recompute_amounts()
        tax_before = self._amt(decl, '23')
        self.ind_dist.rate_percent = 2.0
        decl.action_recompute_amounts()
        tax_after = self._amt(decl, '23')
        self.assertEqual(float_compare(tax_after, tax_before * 2, 0), 0)
        self.ind_dist.rate_percent = 1.0  # restore
        _logger.info('C7-B tax_before=%s tax_after=%s', tax_before, tax_after)

    def test_c7_c_registration_hides_01(self):
        """Ca C — trực tiếp: đăng ký 01 bị chặn, 04 được."""
        Method = self.env['vas.gtgt.tax.method']
        self.assertEqual(
            Method.method_on(self.company_d, '2026-08-01'), 'direct',
        )
        with self.assertRaises(UserError):
            self.env['vas.gtgt.registration'].create({
                'company_id': self.company_d.id,
                'form_type_id': self.form_01.id,
                'period_kind': 'month',
            })
        # 04 đã đăng ký ở seed
        reg04 = self.env['vas.gtgt.registration'].search([
            ('company_id', '=', self.company_d.id),
            ('form_type_id', '=', self.form_04.id),
        ])
        self.assertTrue(reg04)

    def test_c7_d_method_switch_by_date(self):
        """Ca D — đổi PP giữa năm theo ngày hiệu lực."""
        Method = self.env['vas.gtgt.tax.method']
        self.assertEqual(
            Method.method_on(self.company_sw, '2026-08-15'), 'deduction',
        )
        self.assertEqual(
            Method.method_on(self.company_sw, '2026-09-15'), 'direct',
        )
        # Kỳ 08 → 01; kỳ 09 → 04
        d08 = self._make_direct_decl(self.company_sw, self.form_01, 2026, 8)
        self.assertEqual(d08.form_type_id.code, '01/GTGT')
        d09 = self._make_direct_decl(self.company_sw, self.form_04, 2026, 9)
        self.assertEqual(d09.form_type_id.code, '04/GTGT')
        with self.assertRaises(UserError):
            self._make_direct_decl(self.company_sw, self.form_04, 2026, 8)
        with self.assertRaises(UserError):
            self._make_direct_decl(self.company_sw, self.form_01, 2026, 9)
        _logger.info('C7-D aug=01/GTGT sep=04/GTGT')

    def test_c7_e_four_groups_on_04(self):
        """Ca E — bốn nhóm × tỷ lệ đúng."""
        self._sync_co(self.company_d)
        decl = self._make_direct_decl(self.company_d, self.form_04, 2026, 8)
        decl.action_recompute_amounts()
        a22, a23 = self._amt(decl, '22'), self._amt(decl, '23')
        a24, a25 = self._amt(decl, '24'), self._amt(decl, '25')
        a26, a27 = self._amt(decl, '26'), self._amt(decl, '27')
        a28, a29 = self._amt(decl, '28'), self._amt(decl, '29')
        self.assertEqual(float_compare(a22, 10_000_000, 0), 0)
        self.assertEqual(float_compare(a23, 100_000, 0), 0)   # 1%
        self.assertEqual(float_compare(a24, 8_000_000, 0), 0)
        self.assertEqual(float_compare(a25, 400_000, 0), 0)   # 5%
        self.assertEqual(float_compare(a26, 6_000_000, 0), 0)
        self.assertEqual(float_compare(a27, 180_000, 0), 0)   # 3%
        self.assertEqual(float_compare(a28, 4_000_000, 0), 0)
        self.assertEqual(float_compare(a29, 80_000, 0), 0)    # 2%
        _logger.info(
            'C7-E 22=%s/23=%s 24=%s/25=%s 26=%s/27=%s 28=%s/29=%s',
            a22, a23, a24, a25, a26, a27, a28, a29,
        )

    def test_c7_f_undetermined_blocks(self):
        """Ca F — SP chưa nhóm → chặn lập 04."""
        self._sync_co(self.company_d)
        decl = self._make_direct_decl(self.company_d, self.form_04, 2026, 9)
        with self.assertRaises(UserError) as err:
            decl.action_recompute_amounts()
        self.assertIn('CHƯA XÁC ĐỊNH', str(err.exception))
        products, undet = decl._count_undetermined_direct_products()
        self.assertGreaterEqual(len(products), 1)
        _logger.info('C7-F undet_products=%s undet_lines=%s', len(products), undet)

    def test_c7_g_h_form_03_and_neg_carry(self):
        """Ca G+H — mẫu 03 GTGT = DT−GV; âm chuyển kỳ sau."""
        self._sync_co(self.company_g)
        # Giá vốn 45tr — GTGT = 5tr
        Acc = self.env['vas.account']
        acc632 = Acc.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '632'),
        ], limit=1)
        acc111 = Acc.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=like', '111%'),
        ], limit=1)
        journal = self.env['vas.journal'].search([
            ('regime_id', '=', self.regime.id),
        ], limit=1)
        self.env['vas.move'].create({
            'date': '2026-08-20',
            'journal_id': journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'ref': 'C7-GOLD-COGS',
            'company_id': self.company_g.id,
            'currency_id': self.vnd.id,
            'line_ids': [
                Command.create({
                    'account_id': acc632.id, 'debit': 45_000_000, 'credit': 0,
                    'direct_industry_id': self.ind_gold.id,
                    'direct_industry_status': 'resolved',
                    'currency_id': self.vnd.id,
                }),
                Command.create({
                    'account_id': acc111.id, 'debit': 0, 'credit': 45_000_000,
                    'currency_id': self.vnd.id,
                    'tax_status': 'none',
                    'direct_industry_status': 'none',
                }),
            ],
        }).action_post()

        aug = self._make_direct_decl(self.company_g, self.form_03, 2026, 8)
        aug.action_recompute_amounts()
        a22, a23, a26 = self._amt(aug, '22'), self._amt(aug, '23'), self._amt(aug, '26')
        self.assertEqual(float_compare(a22, 50_000_000, 0), 0)
        self.assertEqual(float_compare(a23, 45_000_000, 0), 0)
        self.assertEqual(float_compare(a26, 5_000_000, 0), 0)
        self.assertEqual(float_compare(self._amt(aug, '27'), 500_000, 0), 0)
        aug.action_prepare()
        aug.action_set_state_filed()

        # Kỳ âm: mua 60tr > bán 50tr trên cùng DT — tạo kỳ 09 với cost cao hơn
        self.env['vas.move'].create({
            'date': '2026-09-10',
            'journal_id': journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'ref': 'C7-GOLD-COGS-SEP',
            'company_id': self.company_g.id,
            'currency_id': self.vnd.id,
            'line_ids': [
                Command.create({
                    'account_id': acc632.id, 'debit': 60_000_000, 'credit': 0,
                    'direct_industry_id': self.ind_gold.id,
                    'direct_industry_status': 'resolved',
                    'currency_id': self.vnd.id,
                }),
                Command.create({
                    'account_id': acc111.id, 'debit': 0, 'credit': 60_000_000,
                    'currency_id': self.vnd.id,
                    'tax_status': 'none',
                    'direct_industry_status': 'none',
                }),
            ],
        }).action_post()
        # Bán lại 50tr tháng 9
        inv = self.env['account.move'].with_company(self.company_g).create({
            'move_type': 'out_invoice',
            'company_id': self.company_g.id,
            'journal_id': self.sale_j_g.id,
            'partner_id': self.partner_g.id,
            'invoice_date': '2026-09-15',
            'date': '2026-09-15',
            'ref': 'C7-GOLD-SEP',
            'invoice_line_ids': [Command.create({
                'product_id': self.prod_gold.id,
                'name': self.prod_gold.name,
                'quantity': 1,
                'price_unit': 50_000_000,
                'tax_ids': [Command.set(self.tax10_g.ids)],
            })],
        })
        inv.action_post()
        self._sync_co(self.company_g)

        sep = self._make_direct_decl(self.company_g, self.form_03, 2026, 9)
        sep.action_recompute_amounts()
        # [26] = 50M - 60M - 0 = -10M → amount_neg_carry = 10M
        self.assertEqual(float_compare(self._amt(sep, '26'), -10_000_000, 0), 0)
        sep.action_prepare()
        sep.action_set_state_filed()
        self.assertEqual(float_compare(sep.amount_neg_carry, 10_000_000, 0), 0)

        oct_ = self._make_direct_decl(self.company_g, self.form_03, 2026, 10)
        oct_.action_recompute_amounts()
        self.assertEqual(float_compare(self._amt(oct_, '21'), 10_000_000, 0), 0)
        _logger.info(
            'C7-GH 22=%s 23=%s 26=%s neg_carry=%s oct21=%s',
            a22, a23, a26, sep.amount_neg_carry, self._amt(oct_, '21'),
        )

    def test_c7_i_backfill_preserves_ledger(self):
        """Ca I — backfill ngành: trước/sau bằng tuyệt đối."""
        self._sync_co(self.company_d)
        # Xóa ngành trên dòng để mô phỏng sổ cũ
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_d.id),
            ('account_id.code', '=like', '511%'),
            ('credit', '>', 0),
        ])
        lines.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({
            'direct_industry_id': False,
            'direct_industry_status': 'none',
        })
        Sync = self.env['vas.sync']
        before = Sync._snapshot_ledger_by_account(self.company_d)
        result = Sync.backfill_direct_industry(self.company_d)
        after = result['after']
        self.assertEqual(before, after)
        self.assertEqual(before['move_count'], after['move_count'])
        _logger.info(
            'C7-I move_count=%s filled=%s before_eq_after=%s',
            before['move_count'], result['filled'], before == after,
        )

    def test_c7_j_deduction_company_unchanged(self):
        """Ca J — công ty khấu trừ: tờ 01 vẫn chạy như cũ."""
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        self.assertEqual(decl.form_type_id.code, '01/GTGT')
        self.assertIn('25', decl.line_ids.mapped('code'))
        self.assertGreater(self._amt(decl, '24'), 0)
