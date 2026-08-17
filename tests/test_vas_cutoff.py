# -*- coding: utf-8 -*-
"""P1 — Ngày bắt đầu ghi sổ (cutoff): sync sàn + hàng rào cứng lúc post."""
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_cutoff')
class TestVasCutoff(TransactionCase):

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
                'code': 'TT133', 'name': 'Thông tư 133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2099-06-15'

        cls.env['vas.journal']._connecta_seed_tt133_journals()

        cls.fiscalyear = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-06-01'),
            ('date_to', '>=', '2099-06-30'),
        ], limit=1)
        if not cls.fiscalyear:
            cls.fiscalyear = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        for mid, ds, de in (
            ('05/2099', '2099-05-01', '2099-05-31'),
            ('06/2099', '2099-06-01', '2099-06-30'),
        ):
            period = cls.env['vas.period'].search([
                ('fiscalyear_id', '=', cls.fiscalyear.id),
                ('date_start', '=', ds),
                ('date_end', '=', de),
            ], limit=1)
            if not period:
                cls.env['vas.period'].create({
                    'name': mid,
                    'date_start': ds,
                    'date_end': de,
                    'fiscalyear_id': cls.fiscalyear.id,
                    'state': 'open',
                })
            else:
                period.state = 'open'

        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        cls.acc_411 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '411'),
        ], limit=1)
        assert cls.acc_111 and cls.acc_411, 'Thiếu TK 111/411'
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1) or cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general'),
        ], limit=1)
        assert cls.journal, 'Thiếu sổ nhật ký VAS'

        cls.partner = cls.env['res.partner'].create({
            'name': 'KH Cutoff',
            'company_id': cls.company.id,
            'customer_rank': 1,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'DV Cutoff',
            'type': 'service',
            'list_price': 100_000,
            'taxes_id': [Command.clear()],
            'invoice_policy': 'order',
        })
        cls.sale_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'sale'),
        ], limit=1)
        assert cls.sale_journal, 'Thiếu sale journal'

    def _balanced_move(self, date, move_kind='manual', amount=1_000_000.0, **extra):
        vals = {
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'ref': f'cutoff {date}',
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': self.acc_111.id,
                    'name': 'Nợ',
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': self.vnd.id,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': self.acc_411.id,
                    'name': 'Có',
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': self.vnd.id,
                }),
            ],
        }
        vals.update(extra)
        return self.env['vas.move'].create(vals)

    def _invoice(self, date, amount=100_000.0):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.clear()],
            })],
        })
        inv.action_post()
        return inv

    def test_p1_cutoff_blocks_sync_without_start_date(self):
        self.company.vas_start_date = False
        with self.assertRaises(UserError) as ctx:
            self.env['vas.sync'].sync_company(self.company)
        self.assertIn('Ngày bắt đầu ghi sổ', str(ctx.exception))

    def test_p1_cutoff_only_syncs_on_or_after_start_date(self):
        """Trước cutoff bỏ qua; ≥ cutoff sinh bút toán."""
        before = self._invoice('2099-06-14')
        after = self._invoice('2099-06-15')
        self.env['vas.sync'].sync_company(self.company)

        Move = self.env['vas.move']
        vas_before = Move.search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', before.id),
            ('state', '=', 'posted'),
        ])
        vas_after = Move.search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', after.id),
            ('state', '=', 'posted'),
        ])
        self.assertFalse(
            vas_before,
            f'Chứng từ trước cutoff không được sinh VAS: {vas_before}',
        )
        self.assertTrue(vas_after, 'Chứng từ đúng/sau cutoff phải sinh VAS')
        self.assertEqual(vas_after.move_kind, 'sale_inv')

    def test_p1_post_before_cutoff_blocked(self):
        """1. Post ngày trước cutoff → chặn. So sánh: day_d < cutoff."""
        move = self._balanced_move('2099-06-14')
        with self.assertRaises(UserError) as ctx:
            move.action_post()
        msg = str(ctx.exception)
        self.assertIn('2099-06-14', msg)
        self.assertIn('số dư đầu kỳ', msg.lower())
        self.assertEqual(move.state, 'draft')

    def test_p1_draft_before_cutoff_allowed(self):
        """2. Tạo draft ngày trước cutoff → không chặn (§8.4)."""
        move = self._balanced_move('2099-05-20')
        self.assertEqual(move.state, 'draft')
        self.assertEqual(fields.Date.to_string(move.date), '2099-05-20')

    def test_p1_opening_at_cutoff_posts(self):
        """3. Số dư đầu kỳ qua vas.opening.balance → vẫn post. In ngày thật."""
        opening = self.env['vas.opening.balance'].create({
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date': self.company.vas_start_date,
            'ref': 'SDK cutoff fence',
            'line_ids': [
                Command.create({
                    'account_id': self.acc_111.id,
                    'debit': 5_000_000, 'credit': 0.0,
                }),
                Command.create({
                    'account_id': self.acc_411.id,
                    'debit': 0.0, 'credit': 5_000_000,
                }),
            ],
        })
        opening.action_confirm()
        om = opening.move_id
        print(
            f'\n=== B2.3 OPENING date={om.date} name={om.name} '
            f'kind={om.move_kind} source={om.source_model} ===\n'
        )
        self.assertEqual(opening.state, 'posted')
        self.assertEqual(om.state, 'posted')
        self.assertEqual(om.source_model, 'vas.opening.balance')
        self.assertEqual(
            fields.Date.to_string(om.date),
            fields.Date.to_string(self.company.vas_start_date),
        )

    def test_p1_opening_reopen_reverse_posts(self):
        """4. Mở lại SDK → bút toán đảo vẫn post. In ngày thật."""
        opening = self.env['vas.opening.balance'].create({
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date': self.company.vas_start_date,
            'ref': 'SDK reopen fence',
            'line_ids': [
                Command.create({
                    'account_id': self.acc_111.id,
                    'debit': 4_000_000, 'credit': 0.0,
                }),
                Command.create({
                    'account_id': self.acc_411.id,
                    'debit': 0.0, 'credit': 4_000_000,
                }),
            ],
        })
        opening.action_confirm()
        orig = opening.move_id
        orig_id = orig.id
        opening.action_reopen()
        orig = self.env['vas.move'].browse(orig_id)
        rev = orig.reversal_move_id
        print(
            f'\n=== B2.4 ORIG date={orig.date} name={orig.name} state={orig.state}\n'
            f'=== B2.4 REVERSE date={rev.date} name={rev.name} '
            f'is_reversal={rev.is_reversal} state={rev.state} ===\n'
        )
        self.assertEqual(opening.state, 'draft')
        self.assertEqual(orig.state, 'reversed')
        self.assertTrue(rev)
        self.assertEqual(rev.state, 'posted')
        self.assertTrue(rev.is_reversal)
        self.assertEqual(
            fields.Date.to_string(rev.date),
            fields.Date.to_string(self.company.vas_start_date),
        )

    def test_p1_post_on_cutoff_ok(self):
        """5. Post ngày = đúng cutoff → không chặn (biên của <)."""
        move = self._balanced_move('2099-06-15')
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_p1_post_empty_cutoff_blocked(self):
        """6. Cutoff trống → post bị chặn."""
        self.company.vas_start_date = False
        move = self._balanced_move('2099-06-20')
        with self.assertRaises(UserError) as ctx:
            move.action_post()
        msg = str(ctx.exception)
        self.assertIn('chưa khai ngày bắt đầu ghi sổ', msg.lower())
        self.assertEqual(move.state, 'draft')

    def test_p1_hand_opening_kind_before_cutoff_blocked(self):
        """7. CHỐNG LÁCH: tay chọn move_kind=opening, ngày < cutoff → vẫn chặn."""
        move = self._balanced_move('2099-06-14', move_kind='opening')
        self.assertEqual(move.move_kind, 'opening')
        self.assertFalse(move.source_model)
        with self.assertRaises(UserError) as ctx:
            move.action_post()
        self.assertIn('số dư đầu kỳ', str(ctx.exception).lower())
        self.assertEqual(move.state, 'draft')

    def test_p1_reverse_post_fail_rolls_back_clean(self):
        """S1: action_post đảo nổ (ngày < cutoff) → không để nháp đảo / link / dòng."""
        orig = self._balanced_move('2099-06-20')
        orig.action_post()
        orig_id = orig.id
        orig_name = orig.name
        Move = self.env['vas.move']
        Line = self.env['vas.move.line']
        moves_before = Move.search_count([('company_id', '=', self.company.id)])
        lines_before = Line.search_count([('company_id', '=', self.company.id)])

        with self.assertRaises(UserError):
            orig.action_reverse(reverse_date=fields.Date.to_date('2099-06-01'))

        orig = Move.browse(orig_id)
        self.assertEqual(orig.state, 'posted')
        self.assertFalse(orig.reversal_move_id)
        orphans = Move.search([
            ('is_reversal', '=', True),
            ('company_id', '=', self.company.id),
            ('ref', 'ilike', orig_name),
        ])
        self.assertFalse(orphans, f'Còn nháp đảo dở: {orphans}')
        self.assertEqual(
            Move.search_count([('company_id', '=', self.company.id)]),
            moves_before,
        )
        self.assertEqual(
            Line.search_count([('company_id', '=', self.company.id)]),
            lines_before,
        )