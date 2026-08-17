# -*- coding: utf-8 -*-
"""Chặng 0 — gieo dữ liệu thử GTGT + đo sổ VAS (KHÔNG sửa engine)."""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


PERIOD_END = '2026-08-31'
DATE = '2026-08-10'
DUE_NOT_YET = '2026-09-15'
DUE_OVERDUE = '2026-08-05'


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c0')
class TestGtgtChang0SeedAndMeasure(TransactionCase):
    """Gieo đủ ca GTGT trên DB sạch rồi đo hành vi sổ hiện tại."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls._ensure_period()
        cls._ensure_rules()

        cls.sale_journal = cls._journal('sale')
        cls.purchase_journal = cls._journal('purchase')
        cls.bank_journal = cls._journal('bank')
        cls.cash_journal = cls._journal('cash', code='C0CS', name='GTGT C0 Quỹ')

        cls.tax_sale = {
            10: cls._tax('sale', 10.0, 'GTGT C0 bán 10%'),
            5: cls._tax('sale', 5.0, 'GTGT C0 bán 5%'),
            0: cls._tax('sale', 0.0, 'GTGT C0 bán 0% XK'),
            8: cls._tax('sale', 8.0, 'GTGT C0 bán 8% NQ204'),
        }
        cls.tax_purchase = {
            10: cls._tax('purchase', 10.0, 'GTGT C0 mua 10%'),
            5: cls._tax('purchase', 5.0, 'GTGT C0 mua 5%'),
        }

        cls.partner_customer = cls.env['res.partner'].create({
            'name': 'KH GTGT C0 có MST',
            'vat': '0100123456',
            'company_id': cls.company.id,
            'customer_rank': 1,
        })
        cls.partner_vendor = cls.env['res.partner'].create({
            'name': 'NCC GTGT C0 có MST',
            'vat': '0200987654',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.partner_customs = cls.env['res.partner'].create({
            'name': 'HQ / NSNN GTGT C0',
            'vat': '0300111222',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.partner_no_vat = cls.env['res.partner'].create({
            'name': 'KH GTGT C0 KHÔNG MST',
            'vat': False,
            'company_id': cls.company.id,
            'customer_rank': 1,
        })

        cls.cat = cls.env['product.category'].create({'name': 'GTGT C0 DV'})
        cls.env['vas.account.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': cls.cat.id,
            'revenue_account_id': cls._vas_acc('5111').id,
            'expense_account_id': cls._vas_acc('6422').id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'DV GTGT C0',
            'type': 'service',
            'categ_id': cls.cat.id,
            'list_price': 1_000_000.0,
            'purchase_ok': True,
            'sale_ok': True,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })

        cls.seed = {}
        cls._seed_all()

    @classmethod
    def _vas_acc(cls, code):
        acc = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', code),
        ], limit=1)
        assert acc, f'Thiếu TK VAS {code}'
        return acc

    @classmethod
    def _journal(cls, jtype, code=None, name=None):
        journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', jtype),
        ], limit=1)
        if journal:
            return journal
        return cls.env['account.journal'].create({
            'name': name or f'GTGT C0 {jtype}',
            'code': code or f'C0{jtype[:2].upper()}',
            'type': jtype,
            'company_id': cls.company.id,
        })

    @classmethod
    def _tax(cls, use, amount, name):
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', use),
            ('amount', '=', amount),
            ('amount_type', '=', 'percent'),
            ('name', '=', name),
        ], limit=1)
        if existing:
            return existing
        template = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', use),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if template:
            return template.copy({'name': name, 'amount': amount})
        return Tax.create({
            'name': name,
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': use,
            'company_id': cls.company.id,
        })

    @classmethod
    def _ensure_period(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', DATE),
            ('date_to', '>=', DATE),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2026',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})
        # Kỳ 2027 cho HĐ sau khi NQ 204 hết hiệu lực
        fy27 = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2027-01-15'),
            ('date_to', '>=', '2027-01-15'),
        ], limit=1)
        if not fy27:
            fy27 = cls.env['vas.fiscalyear'].create({
                'name': '2027',
                'date_from': '2027-01-01',
                'date_to': '2027-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy27.period_ids:
            fy27.action_generate_periods()
        else:
            fy27.period_ids.write({'state': 'open'})
        cls.period_end = PERIOD_END

    @classmethod
    def _ensure_rules(cls):
        Rule = cls.env['vas.rule']
        regime = cls.regime
        if not Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R01')], limit=1):
            Rule.create({
                'code': 'R01', 'name': 'Hóa đơn bán hàng', 'regime_id': regime.id,
                'event_type': 'sale_invoice', 'sequence': 10, 'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': 10, 'side': 'debit',
                        'account_selector': 'partner_receivable',
                        'amount_selector': 'total',
                    }),
                    Command.create({
                        'sequence': 20, 'side': 'credit',
                        'account_selector': 'product_revenue',
                        'amount_selector': 'untaxed',
                    }),
                    Command.create({
                        'sequence': 30, 'side': 'credit',
                        'account_selector': 'tax_output',
                        'amount_selector': 'tax',
                    }),
                ],
            })
        if not Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R08')], limit=1):
            Rule.create({
                'code': 'R08', 'name': 'Chi phí mua ngoài', 'regime_id': regime.id,
                'event_type': 'purchase_service', 'sequence': 48, 'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': 10, 'side': 'debit',
                        'account_selector': 'product_expense',
                        'amount_selector': 'untaxed',
                    }),
                    Command.create({
                        'sequence': 20, 'side': 'debit',
                        'account_selector': 'tax_input',
                        'amount_selector': 'tax',
                    }),
                    Command.create({
                        'sequence': 30, 'side': 'credit',
                        'account_selector': 'partner_payable',
                        'amount_selector': 'total',
                    }),
                ],
            })
        if not Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R18')], limit=1):
            Rule.create({
                'code': 'R18', 'name': 'Chi trả NCC', 'regime_id': regime.id,
                'event_type': 'payment_out', 'sequence': 60, 'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': 10, 'side': 'debit',
                        'account_selector': 'partner_payable',
                        'amount_selector': 'paid',
                    }),
                    Command.create({
                        'sequence': 20, 'side': 'credit',
                        'account_selector': 'bank_cash',
                        'amount_selector': 'paid',
                    }),
                ],
            })

    @classmethod
    def _out_invoice(cls, key, partner, lines, date=DATE):
        inv_lines = []
        for price, tax in lines:
            vals = {
                'product_id': cls.product.id,
                'name': f'{cls.product.name} {key}',
                'quantity': 1.0,
                'price_unit': price,
            }
            if tax:
                vals['tax_ids'] = [Command.set(tax.ids)]
            else:
                vals['tax_ids'] = [Command.clear()]
            inv_lines.append(Command.create(vals))
        move = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': cls.sale_journal.id,
            'company_id': cls.company.id,
            'invoice_line_ids': inv_lines,
            'ref': f'GTGT-C0-{key}',
        })
        move.action_post()
        cls.seed[key] = move
        return move

    @classmethod
    def _in_invoice(cls, key, partner, lines, date=DATE, due=None):
        inv_lines = []
        for price, tax in lines:
            vals = {
                'product_id': cls.product.id,
                'name': f'{cls.product.name} {key}',
                'quantity': 1.0,
                'price_unit': price,
            }
            if tax:
                vals['tax_ids'] = [Command.set(tax.ids)]
            else:
                vals['tax_ids'] = [Command.clear()]
            inv_lines.append(Command.create(vals))
        move = cls.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': cls.purchase_journal.id,
            'company_id': cls.company.id,
            'invoice_line_ids': inv_lines,
            'ref': f'GTGT-C0-{key}',
        })
        move.action_post()
        if due:
            move.write({'invoice_date_due': due})
        cls.seed[key] = move
        return move

    @classmethod
    def _pay_bill(cls, bill, journal, key):
        wiz = cls.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=bill.ids,
        ).create({
            'payment_date': DATE,
            'journal_id': journal.id,
            'amount': bill.amount_residual,
        })
        payment = wiz._create_payments()[:1]
        if payment.state in ('draft', 'in_process'):
            payment.action_post()
        cls.seed[key] = payment
        return payment

    @classmethod
    def _seed_all(cls):
        cls._out_invoice('sale_10', cls.partner_customer, [
            (1_000_000.0, cls.tax_sale[10]),
        ])
        cls._out_invoice('sale_5', cls.partner_customer, [
            (1_000_000.0, cls.tax_sale[5]),
        ])
        cls._out_invoice('sale_0_export', cls.partner_customer, [
            (2_000_000.0, cls.tax_sale[0]),
        ])
        cls._out_invoice('sale_exempt', cls.partner_customer, [
            (1_500_000.0, None),
        ])
        cls._out_invoice('sale_multi', cls.partner_customer, [
            (1_000_000.0, cls.tax_sale[10]),
            (2_000_000.0, cls.tax_sale[5]),
        ])
        cls._out_invoice('sale_8', cls.partner_customer, [
            (1_000_000.0, cls.tax_sale[8]),
        ])
        cls._out_invoice('sale_no_vat_partner', cls.partner_no_vat, [
            (500_000.0, cls.tax_sale[10]),
        ])
        # Sau hết hiệu lực NQ 204: 10% vẫn hợp lệ; 8% phải báo ngoài hiệu lực
        cls._out_invoice(
            'sale_10_after_nq204', cls.partner_customer,
            [(1_000_000.0, cls.tax_sale[10])],
            date='2027-01-15',
        )
        cls._out_invoice(
            'sale_8_expired', cls.partner_customer,
            [(1_000_000.0, cls.tax_sale[8])],
            date='2027-01-15',
        )

        cls._in_invoice('purchase_10', cls.partner_vendor, [
            (1_000_000.0, cls.tax_purchase[10]),
        ])
        cls._in_invoice('purchase_multi', cls.partner_vendor, [
            (1_000_000.0, cls.tax_purchase[10]),
            (2_000_000.0, cls.tax_purchase[5]),
        ])

        bill_bank = cls._in_invoice('purchase_paid_bank', cls.partner_vendor, [
            (1_000_000.0, cls.tax_purchase[10]),
        ])
        cls._pay_bill(bill_bank, cls.bank_journal, 'pay_bank')

        bill_cash_big = cls._in_invoice('purchase_paid_cash_over5m', cls.partner_vendor, [
            (5_000_000.0, cls.tax_purchase[10]),
        ])
        cls._pay_bill(bill_cash_big, cls.cash_journal, 'pay_cash_over5m')

        cls._in_invoice(
            'purchase_deferred_not_due', cls.partner_vendor,
            [(800_000.0, cls.tax_purchase[10])],
            due=DUE_NOT_YET,
        )
        cls._in_invoice(
            'purchase_deferred_overdue', cls.partner_vendor,
            [(900_000.0, cls.tax_purchase[10])],
            due=DUE_OVERDUE,
        )

        bill_a = cls._in_invoice('purchase_cash_pair_a', cls.partner_vendor, [
            (2_500_000.0, cls.tax_purchase[10]),
        ])
        bill_b = cls._in_invoice('purchase_cash_pair_b', cls.partner_vendor, [
            (2_500_000.0, cls.tax_purchase[10]),
        ])
        cls._pay_bill(bill_a, cls.cash_journal, 'pay_cash_pair_a')
        cls._pay_bill(bill_b, cls.cash_journal, 'pay_cash_pair_b')

        decl = cls.env['vas.import.vat'].create({
            'date': DATE,
            'partner_id': cls.partner_customs.id,
            'amount_vat': 300_000.0,
            'company_id': cls.company.id,
            'regime_id': cls.regime.id,
            'ref': 'TK GTGT C0 NK',
        })
        decl.action_confirm()
        cls.seed['import_vat'] = decl

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2026-01-01', date_to='2027-12-31',
        )

    def _vas_for_invoice(self, invoice):
        kinds = ('sale_inv', 'purchase_inv', 'expense', 'revenue', 'import_vat')
        return self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', invoice.id),
            ('move_kind', 'in', kinds),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])

    def _tax_lines(self, moves, codes=('33311', '1331', '33312', '133', '3331')):
        return moves.mapped('line_ids').filtered(
            lambda l: (l.account_id.code or '') in codes
        )

    def _dump(self, title, payload):
        print(f'\n=== GTGT_C0::{title} ===')
        if isinstance(payload, dict):
            for k, v in payload.items():
                print(f'  {k}: {v}')
        else:
            print(payload)

    def test_a_seed_loads(self):
        """A — bộ dữ liệu thử dựng được, không lỗi."""
        self.assertIn('sale_multi', self.seed)
        self.assertIn('purchase_multi', self.seed)
        self.assertIn('import_vat', self.seed)
        self.assertTrue(self.partner_customer.vat)
        self.assertTrue(self.partner_vendor.vat)
        self.assertFalse(self.partner_no_vat.vat)
        sale = [k for k in self.seed if k.startswith('sale_')]
        purchase = [k for k in self.seed if k.startswith('purchase_')]
        self.assertGreaterEqual(len(sale), 9)
        self.assertGreaterEqual(len(purchase), 8)
        self._dump('A_seed', {
            'sale_keys': sorted(sale),
            'purchase_keys': sorted(purchase),
            'import_vat_state': self.seed['import_vat'].state,
            'partners_with_vat': [
                self.partner_customer.vat,
                self.partner_vendor.vat,
                self.partner_customs.vat,
            ],
            'partner_no_vat': bool(self.partner_no_vat.vat),
        })

    def test_b_multi_rate_invoices_exist(self):
        """B — có ≥1 HĐ bán và ≥1 HĐ mua nhiều thuế suất."""
        sale = self.seed['sale_multi']
        purchase = self.seed['purchase_multi']
        sale_rates = {t.amount for line in sale.invoice_line_ids for t in line.tax_ids}
        purchase_rates = {
            t.amount for line in purchase.invoice_line_ids for t in line.tax_ids
        }
        self.assertGreaterEqual(len(sale_rates), 2, sale_rates)
        self.assertGreaterEqual(len(purchase_rates), 2, purchase_rates)
        self._dump('B_multi_rate', {
            'sale_multi': sale.name,
            'sale_rates': sorted(sale_rates),
            'sale_amount_tax': sale.amount_tax,
            'purchase_multi': purchase.name,
            'purchase_rates': sorted(purchase_rates),
            'purchase_amount_tax': purchase.amount_tax,
        })

    def test_c_sync_creates_vas_for_seeded(self):
        """C — đồng bộ xong, mỗi chứng từ gieo có bút toán VAS."""
        self._sync()
        missing = []
        for key, rec in self.seed.items():
            if key.startswith('pay_'):
                moves = self.env['vas.move'].search([
                    ('source_model', '=', 'account.payment'),
                    ('source_res_id', '=', rec.id),
                    ('state', '=', 'posted'),
                    ('is_reversal', '=', False),
                ])
            elif key == 'import_vat':
                moves = rec.accrual_move_id
            else:
                moves = self._vas_for_invoice(rec)
            if not moves:
                missing.append(key)
        self._dump('C_sync_coverage', {
            'missing': missing,
            'seeded': sorted(self.seed.keys()),
        })
        self.assertFalse(missing, f'Thiếu bút toán VAS cho: {missing}')

    def test_d_measure_multi_rate_split(self):
        """D — đo: sổ tách hay không tách thuế suất trên HĐ đa suất."""
        self._sync()
        report = {}
        for key in ('sale_multi', 'purchase_multi'):
            inv = self.seed[key]
            moves = self._vas_for_invoice(inv)
            tax_lines = self._tax_lines(moves)
            amounts = [
                {
                    'account': l.account_id.code,
                    'debit': l.debit,
                    'credit': l.credit,
                    'tax_id': l.tax_id.id or False,
                    'tax_code': l.tax_id.code if l.tax_id else False,
                }
                for l in tax_lines
            ]
            odoo_by_rate = defaultdict(float)
            for line in inv.invoice_line_ids.filtered(
                lambda l: l.display_type not in ('line_section', 'line_note')
            ):
                tax_amt = abs((line.price_total or 0.0) - (line.price_subtotal or 0.0))
                rates = line.tax_ids.mapped('amount') or [None]
                odoo_by_rate[rates[0] if rates else None] += tax_amt
            report[key] = {
                'invoice': inv.name,
                'odoo_amount_tax': inv.amount_tax,
                'odoo_by_rate': dict(odoo_by_rate),
                'vas_move_count': len(moves),
                'vas_tax_line_count': len(tax_lines),
                'vas_tax_lines': amounts,
                'split_by_rate': (
                    len(tax_lines) >= 2
                    and any(a['tax_id'] for a in amounts)
                ),
            }
        self._dump('D_multi_rate_measure', report)
        for key, data in report.items():
            self.assertEqual(
                data['vas_tax_line_count'], 2,
                f'{key}: sau 1A phải tách 2 dòng thuế, got {data}',
            )
            self.assertTrue(
                data['split_by_rate'],
                f'{key}: sau 1A phải tách theo suất + tax_id',
            )
            codes = {a['tax_code'] for a in data['vas_tax_lines']}
            self.assertEqual(codes, {'GTGT_5', 'GTGT_10'}, codes)

    def test_e_measure_tax_amount_delta(self):
        """E — lệch tiền thuế VAS vs Odoo theo từng chứng từ."""
        self._sync()
        deltas = []
        inv_keys = [k for k, v in self.seed.items() if v._name == 'account.move']
        for key in sorted(inv_keys):
            inv = self.seed[key]
            moves = self._vas_for_invoice(inv)
            tax_lines = self._tax_lines(moves)
            vas_tax = sum(abs(l.debit - l.credit) for l in tax_lines)
            odoo_tax = abs(inv.amount_tax or 0.0)
            diff = round(vas_tax - odoo_tax, 2)
            deltas.append({
                'key': key,
                'invoice': inv.name,
                'move_type': inv.move_type,
                'odoo_tax': odoo_tax,
                'vas_tax': vas_tax,
                'delta': diff,
                'vas_tax_line_count': len(tax_lines),
            })
        nonzero = [d for d in deltas if float_compare(d['delta'], 0.0, 2) != 0]
        self._dump('E_tax_delta', {'all': deltas, 'nonzero': nonzero})

    def test_f_reverse_trace_and_vat_path(self):
        """F — đủ 4 trường bảng kê? MST thiếu do cấu trúc hay dữ liệu?"""
        self._sync()
        samples = []
        for key in (
            'sale_10', 'sale_multi', 'sale_no_vat_partner',
            'purchase_10', 'purchase_multi',
        ):
            inv = self.seed[key]
            moves = self._vas_for_invoice(inv)
            tax_lines = self._tax_lines(moves)
            for line in tax_lines:
                move = line.move_id
                inv_number = inv_date = partner_name = partner_vat = None
                if move.source_model == 'account.move' and move.source_res_id:
                    src = self.env['account.move'].browse(move.source_res_id).exists()
                    if src:
                        inv_number = src.name
                        inv_date = src.invoice_date
                        partner = src.partner_id or line.partner_id
                        partner_name = partner.name if partner else None
                        partner_vat = partner.vat if partner else None
                samples.append({
                    'key': key,
                    'line_id': line.id,
                    'inv_number': inv_number,
                    'inv_date': str(inv_date) if inv_date else None,
                    'partner_name': partner_name,
                    'partner_vat': partner_vat,
                    'complete_four': bool(
                        inv_number and inv_date and partner_name and partner_vat
                    ),
                    'partner_has_vat_on_master': bool(inv.partner_id.vat),
                    'path_field_partner_vat_exists': (
                        'vat' in self.env['res.partner']._fields
                    ),
                    'path_source_to_am': move.source_model == 'account.move',
                    'line_partner_id': line.partner_id.id or False,
                })

        complete = [s for s in samples if s['complete_four']]
        missing = [s for s in samples if not s['complete_four']]
        structure_ok_data_empty = [
            s for s in missing
            if s['path_field_partner_vat_exists']
            and s['path_source_to_am']
            and s['inv_number'] and s['inv_date'] and s['partner_name']
            and not s['partner_vat']
        ]
        self._dump('F_reverse_trace', {
            'tax_line_samples': len(samples),
            'complete_four': len(complete),
            'missing_at_least_one': len(missing),
            'mst_structure_ok_data_empty': len(structure_ok_data_empty),
            'samples': samples,
        })
        self.assertTrue(
            all(s['path_field_partner_vat_exists'] for s in samples),
            'Field res.partner.vat phải tồn tại',
        )
        with_vat = [s for s in samples if s['partner_has_vat_on_master']]
        self.assertTrue(with_vat, 'Cần ít nhất một dòng thuế từ đối tác có MST')
        self.assertTrue(
            all(s['complete_four'] for s in with_vat),
            f'Có đường + có dữ liệu MST mà vẫn thiếu 4 trường: {with_vat}',
        )
        no_vat = [s for s in samples if s['key'] == 'sale_no_vat_partner']
        self.assertTrue(no_vat)
        self.assertTrue(all(
            s['path_source_to_am'] and not s['partner_vat'] for s in no_vat
        ))

    def test_g_payment_and_due_seed_facts(self):
        """Bổ sung đo: phương thức TT + hạn thanh toán trên bộ gieo."""
        bank = self.seed['purchase_paid_bank']
        cash = self.seed['purchase_paid_cash_over5m']
        not_due = self.seed['purchase_deferred_not_due']
        overdue = self.seed['purchase_deferred_overdue']
        pair_a = self.seed['purchase_cash_pair_a']
        pair_b = self.seed['purchase_cash_pair_b']

        self.assertEqual(bank.payment_state, 'paid')
        self.assertEqual(cash.payment_state, 'paid')
        self.assertGreater(cash.amount_total, 5_000_000.0)
        self.assertEqual(self.seed['pay_cash_over5m'].journal_id.type, 'cash')
        self.assertEqual(self.seed['pay_bank'].journal_id.type, 'bank')

        self.assertEqual(str(not_due.invoice_date_due), DUE_NOT_YET)
        self.assertEqual(str(overdue.invoice_date_due), DUE_OVERDUE)
        self.assertLess(overdue.invoice_date_due, fields.Date.to_date(PERIOD_END))
        self.assertGreater(not_due.invoice_date_due, fields.Date.to_date(PERIOD_END))
        self.assertIn(not_due.payment_state, ('not_paid', 'partial'))
        self.assertIn(overdue.payment_state, ('not_paid', 'partial'))

        self.assertEqual(pair_a.partner_id, pair_b.partner_id)
        self.assertEqual(pair_a.invoice_date, pair_b.invoice_date)
        self.assertLess(pair_a.amount_total, 5_000_000.0)
        self.assertLess(pair_b.amount_total, 5_000_000.0)
        self.assertGreater(pair_a.amount_total + pair_b.amount_total, 5_000_000.0)
        self.assertEqual(self.seed['pay_cash_pair_a'].journal_id.type, 'cash')
        self.assertEqual(self.seed['pay_cash_pair_b'].journal_id.type, 'cash')

        decl = self.seed['import_vat']
        self.assertEqual(decl.state, 'confirmed')
        self.assertTrue(decl.accrual_move_id)

        self._dump('G_payment_due_facts', {
            'bank_paid': bank.name,
            'cash_over5m_total': cash.amount_total,
            'due_not_yet': str(not_due.invoice_date_due),
            'due_overdue': str(overdue.invoice_date_due),
            'pair_totals': [pair_a.amount_total, pair_b.amount_total],
            'import_vat_move': decl.accrual_move_id.name,
        })
