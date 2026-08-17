# -*- coding: utf-8 -*-
"""W11 — bản B01a đã lập (snapshot): không tính lại, stale, đã nộp, chi tiết, benchmark."""
import time
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B01aSnapshot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'W11-Snap Thử',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2092-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'W11-Snap-2092',
            'date_from': '2092-01-01',
            'date_to': '2092-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['vas.period'].create({
            'name': '03/2092',
            'date_start': '2092-03-01',
            'date_end': '2092-03-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        cls.partner = cls.env['res.partner'].create({
            'name': 'W11 Snap Partner',
            'company_id': cls.company.id,
        })

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post(self, date, lines, ref='W11-SNAP'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': 'manual',
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
                'partner_id': partner.id if partner else False,
            }) for acc, name, deb, cre, partner in lines],
        })
        move.action_post()
        return move

    def _opts(self):
        return {
            'company_id': self.company.id,
            'period_from_id': self.period.id,
            'period_to_id': self.period.id,
            'hide_reversed': True,
        }

    def _generate(self):
        return self.env['vas.report.snapshot'].generate_b01a(
            self.company, self.period, self.period, hide_reversed=True,
        )

    def test_01_reopen_does_not_reaggregate(self):
        self._post('2092-03-10', [
            (self._acc('111'), 'TM', 5_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 5_000_000, False),
        ])
        snap = self._generate()
        data1 = snap.get_report_data()
        calls = []
        Snap = type(snap)
        orig = Snap._books_aggregate_buckets

        def wrapped(this, *a, **k):
            calls.append(1)
            return orig(this, *a, **k)

        Snap._books_aggregate_buckets = wrapped
        try:
            data2 = self.env['vas.b01a.wizard'].get_report_data({
                **self._opts(), 'snapshot_id': snap.id,
            })
            data3 = snap.get_report_data()
        finally:
            Snap._books_aggregate_buckets = orig
        self.assertEqual(calls, [], 'Mở lại bản đã lưu không được gọi gom sổ')
        self.assertTrue(data2['meta'].get('from_snapshot'))
        self.assertEqual(data1['meta']['snapshot_id'], data2['meta']['snapshot_id'])
        # values: code, name, note_b09, opening, closing
        am1 = {l['values'][0]: l['values'][4] for l in data1['lines']}
        am3 = {l['values'][0]: l['values'][4] for l in data3['lines']}
        self.assertEqual(am1['200'], am3['200'])

    def test_02_new_move_keeps_old_amounts_and_stales(self):
        self._post('2092-03-11', [
            (self._acc('111'), 'TM', 3_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 3_000_000, False),
        ])
        snap = self._generate()
        am_before = {
            l.code: l.amount_closing for l in snap.line_ids if l.code == '110'
        }
        # Lùi thời điểm lập để create_date move mới > date_computed
        past = fields.Datetime.now() - timedelta(hours=1)
        snap.write({'date_computed': past})
        self._post('2092-03-12', [
            (self._acc('111'), 'TM2', 7_000_000, 0, False),
            (self._acc('4111'), 'Von2', 0, 7_000_000, False),
        ])
        snap.invalidate_recordset(['ledger_changed', 'ledger_stale_message'])
        self.assertTrue(snap.ledger_changed)
        self.assertIn('có thể đã cũ', snap.ledger_stale_message or '')
        self.assertEqual(
            float_compare(am_before['110'], snap.line_ids.filtered(
                lambda l: l.code == '110'
            ).amount_closing, 2),
            0,
            'Số bản cũ không đổi khi sổ phát sinh thêm',
        )
        data = snap.get_report_data()
        self.assertTrue(data['meta']['ledger_changed'])

    def test_03_submitted_blocks_write_unlink_model(self):
        self._post('2092-03-13', [
            (self._acc('111'), 'TM', 1_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 1_000_000, False),
        ])
        snap = self._generate()
        line = snap.line_ids[:1]
        detail = line.detail_ids[:1]
        snap.action_mark_submitted()
        self.assertTrue(snap.is_submitted)
        with self.assertRaises(UserError):
            snap.write({'name': 'hack'})
        with self.assertRaises(UserError):
            snap.unlink()
        with self.assertRaises(UserError):
            line.write({'amount_closing': 999})
        with self.assertRaises(UserError):
            line.unlink()
        if detail:
            with self.assertRaises(UserError):
                detail.write({'amount_closing': 1})
            with self.assertRaises(UserError):
                detail.unlink()

    def test_04_detail_accounts_and_partner_split(self):
        cust_a = self.env['res.partner'].create({
            'name': 'Snap KH A', 'company_id': self.company.id,
        })
        cust_b = self.env['res.partner'].create({
            'name': 'Snap KH B', 'company_id': self.company.id,
        })
        self._post('2092-03-14', [
            (self._acc('131'), 'AR A', 10_000_000, 0, cust_a),
            (self._acc('511'), 'DT', 0, 10_000_000, False),
        ])
        self._post('2092-03-14', [
            (self._acc('111'), 'TT', 4_000_000, 0, False),
            (self._acc('131'), 'Pre B', 0, 4_000_000, cust_b),
        ])
        self._post('2092-03-14', [
            (self._acc('111'), 'TM', 6_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 6_000_000, False),
        ])
        snap = self._generate()
        line_131 = snap.line_ids.filtered(lambda l: l.code == '131')
        line_312 = snap.line_ids.filtered(lambda l: l.code == '312')
        self.assertEqual(float_compare(line_131.amount_closing, 10_000_000, 2), 0)
        self.assertEqual(float_compare(line_312.amount_closing, 4_000_000, 2), 0)
        self.assertTrue(line_131.detail_ids)
        self.assertTrue(line_131.aggregate_by_partner)
        partners_131 = line_131.detail_ids.mapped('partner_id')
        self.assertIn(cust_a, partners_131)
        det_a = line_131.detail_ids.filtered(lambda d: d.partner_id == cust_a)
        self.assertEqual(float_compare(det_a.amount_closing, 10_000_000, 2), 0)
        det_312 = line_312.detail_ids.filtered(lambda d: d.partner_id == cust_b)
        self.assertTrue(det_312)
        self.assertEqual(float_compare(det_312.amount_closing, 4_000_000, 2), 0)
        # Tiền: chi tiết theo TK
        line_110 = snap.line_ids.filtered(lambda l: l.code == '110')
        self.assertTrue(line_110.detail_ids.filtered(lambda d: d.account_code == '111'))

    def test_05_regenerate_keeps_old(self):
        self._post('2092-03-15', [
            (self._acc('111'), 'TM', 2_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 2_000_000, False),
        ])
        old = self._generate()
        old_id = old.id
        action = old.action_regenerate()
        self.assertEqual(action.get('type'), 'ir.actions.client')
        self.assertEqual(action.get('tag'), 'vas_report_client')
        new = self.env['vas.report.snapshot'].browse(
            action['context']['snapshot_id']
        )
        self.assertNotEqual(old_id, new.id)
        self.assertTrue(old.exists())
        self.assertEqual(
            self.env['vas.report.snapshot'].browse(old_id).line_ids[:1].amount_closing,
            old.line_ids.filtered(lambda l: l.code == '110').amount_closing,
        )

    def test_06_w11_bctc_regenerate_matches_acceptance(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search([('name', '=', 'W11-Thử BCTC')], limit=1)
        self.assertTrue(company)
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
        from odoo.addons.connecta_vas.models.res_company import (
            W11_BCTC_A28_DEPOSIT,
            W11_BCTC_EXPECT_BS,
        )
        by = {l.code: l.amount_closing for l in snap.line_ids}
        self.assertEqual(float_compare(by['200'], by['500'], 2), 0)
        self.assertEqual(float_compare(by['200'], W11_BCTC_EXPECT_BS, 2), 0)
        self.assertEqual(float_compare(by['500'], W11_BCTC_EXPECT_BS, 2), 0)
        self.assertEqual(float_compare(by['200'], by['500'], 2), 0)
        self.assertEqual(float_compare(by['131'], 38_000_000, 2), 0)
        self.assertEqual(float_compare(by['312'], 15_000_000, 2), 0)
        self.assertEqual(float_compare(by['132'], 10_000_000, 2), 0)
        self.assertEqual(float_compare(by['311'], 35_000_000, 2), 0)
        # A28 TG kỳ hạn trên 12811 → B01a 122; không dư 1281 cha (C1)
        self.assertEqual(
            float_compare(by.get('122', 0.0), W11_BCTC_A28_DEPOSIT, 2), 0,
        )
        self.assertFalse(snap.warning_text)

    def _count_generate_queries(self, company, period_from, period_to):
        """Đếm SQL chỉ trong generate_b01a — dùng lại được cho B02/B09."""
        self.env.flush_all()
        with VasQueryCounter(self.env.cr) as qc:
            snap = self.env['vas.report.snapshot'].generate_b01a(
                company, period_from, period_to, hide_reversed=True,
            )
            self.env.flush_all()
        return qc.count, snap

    def test_07_query_count_stable_three_runs(self):
        """Cách đo sạch: 3 lần lập trên cùng sổ → cùng số câu SQL."""
        self._post('2092-03-20', [
            (self._acc('111'), 'TM', 4_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 4_000_000, False),
        ])
        # Warm-up (không tính) — nạp cache ORM meta
        self._count_generate_queries(self.company, self.period, self.period)
        counts = []
        for _i in range(3):
            n, _snap = self._count_generate_queries(
                self.company, self.period, self.period,
            )
            counts.append(n)
        print('QUERY_STABLE_3RUNS', counts)
        self.assertEqual(
            counts[0], counts[1],
            'Lần 1 (%s) ≠ lần 2 (%s)' % (counts[0], counts[1]),
        )
        self.assertEqual(
            counts[1], counts[2],
            'Lần 2 (%s) ≠ lần 3 (%s)' % (counts[1], counts[2]),
        )

    def test_08_query_count_not_linear_in_indicators(self):
        """Lưới B01a/B02/B09: nhân đôi chỉ tiêu không được nhân đôi số câu SQL."""
        self._post('2092-03-21', [
            (self._acc('111'), 'TM', 1_500_000, 0, False),
            (self._acc('4111'), 'Von', 0, 1_500_000, False),
        ])
        # Warm-up
        self._count_generate_queries(self.company, self.period, self.period)
        q_base, snap_base = self._count_generate_queries(
            self.company, self.period, self.period,
        )
        n_base = self.env['vas.report.line'].search_count([
            ('form_code', '=', 'B01a-DNN'),
            ('regime_id', '=', self.regime.id),
            ('active', '=', True),
        ])
        self.assertGreaterEqual(n_base, 40)
        self.assertEqual(len(snap_base.line_ids), n_base)

        # Nhân đôi chỉ tiêu (force_zero — không cần TK trên sổ)
        probes = self.env['vas.report.line']
        for i in range(n_base):
            probes |= self.env['vas.report.line'].create({
                'sequence': 9000 + i,
                'code': 'Z%03d' % i,
                'name': 'Probe scale %s' % i,
                'form_code': 'B01a-DNN',
                'regime_id': self.regime.id,
                'line_role': 'detail',
                'amount_source': 'force_zero',
                'force_zero_currency_id': self.env.ref('base.VND').id,
                'basis_kind': 'chot_connecta',
                'is_system': False,
                'active': True,
            })
        self.addCleanup(probes.unlink)
        q_double, snap_double = self._count_generate_queries(
            self.company, self.period, self.period,
        )
        self.assertEqual(len(snap_double.line_ids), n_base * 2)
        delta = q_double - q_base
        # Ngưỡng cố định — không tuyến tính theo số chỉ tiêu thêm
        max_delta = 25
        print(
            'QUERY_SCALE base=%s double=%s delta=%s n_base=%s max_delta=%s'
            % (q_base, q_double, delta, n_base, max_delta)
        )
        self.assertLessEqual(
            delta, max_delta,
            'Số câu SQL tăng %s khi thêm %s chỉ tiêu (base=%s double=%s) — '
            'vượt ngưỡng %s (ghi theo lô phải giữ gần như phẳng).'
            % (delta, n_base, q_base, q_double, max_delta),
        )
        self.assertLess(
            delta, n_base,
            'Delta %s gần tuyến tính với %s chỉ tiêu thêm — tái phát INSERT từng dòng.'
            % (delta, n_base),
        )


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B01aBenchmark(TransactionCase):
    """Đo tốc độ trên công ty thử RIÊNG — dọn bằng rollback TransactionCase."""

    def test_benchmark_300k_lines(self):
        from calendar import monthrange

        cr = self.env.cr
        cr.execute("""
            SELECT indexname, indexdef
              FROM pg_indexes
             WHERE tablename = 'vas_move_line'
               AND (
                    indexdef ILIKE '%account_id%'
                 OR indexdef ILIKE '%date%'
                 OR indexdef ILIKE '%partner_id%'
               )
             ORDER BY indexname
        """)
        idx_rows = cr.fetchall()
        idx_text = '\n'.join('%s | %s' % (n, d) for n, d in idx_rows)
        has_account = any('account_id' in (d or '') for _n, d in idx_rows)
        has_date = any('date' in (d or '') for _n, d in idx_rows)
        has_partner = any('partner_id' in (d or '') for _n, d in idx_rows)
        self.assertTrue(has_account, 'THIẾU index account_id:\n' + idx_text)
        self.assertTrue(has_date, 'THIẾU index date:\n' + idx_text)
        self.assertTrue(has_partner, 'THIẾU index partner_id:\n' + idx_text)
        print('INDEX_OK account=%s date=%s partner=%s' % (
            has_account, has_date, has_partner,
        ))

        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-Bench 300k',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2093-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = self.env['vas.fiscalyear'].create({
            'name': 'Bench-2093',
            'date_from': '2093-01-01',
            'date_to': '2093-12-31',
            'state': 'open',
            'company_id': company.id,
        })
        periods = []
        for m in range(1, 13):
            start = '2093-%02d-01' % m
            end = '2093-%02d-%02d' % (m, monthrange(2093, m)[1])
            periods.append(self.env['vas.period'].create({
                'name': '%02d/2093' % m,
                'date_start': start,
                'date_end': end,
                'fiscalyear_id': fy.id,
                'state': 'open',
            }))
        partners = self.env['res.partner'].create([
            {'name': 'Bench P %s' % i, 'company_id': company.id}
            for i in range(50)
        ])
        acc_111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        acc_411 = self.env.ref('connecta_vas.vas_account_tt133_4111')
        acc_131 = self.env.ref('connecta_vas.vas_account_tt133_131')
        acc_511 = self.env.ref('connecta_vas.vas_account_tt133_511')

        n_moves = 150_000
        print('BENCH_SEED start moves=%s' % n_moves)
        t_seed0 = time.perf_counter()
        move_rows = []
        for i in range(n_moves):
            month = (i % 12) + 1
            day = (i % 28) + 1
            move_rows.append((
                'BN/%s' % i,
                '2093-%02d-%02d' % (month, day),
                journal.id, regime.id, 'manual', 'posted',
                vnd.id, company.id, False,
            ))
        for i in range(0, len(move_rows), 5000):
            cr.executemany(
                """
                INSERT INTO vas_move
                    (name, date, journal_id, regime_id, move_kind, state,
                     currency_id, company_id, is_reversal,
                     create_uid, write_uid, create_date, write_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,1,NOW(),NOW())
                """,
                move_rows[i:i + 5000],
            )
        cr.execute(
            """
            SELECT id, date FROM vas_move
             WHERE company_id = %s AND name LIKE 'BN/%%'
             ORDER BY id
            """,
            [company.id],
        )
        move_ids = cr.fetchall()
        self.assertEqual(len(move_ids), n_moves)
        partner_ids = partners.ids
        line_rows = []
        for idx, (mid, mdate) in enumerate(move_ids):
            pid = partner_ids[idx % len(partner_ids)]
            if idx % 3 == 0:
                line_rows.append((
                    mid, 10, acc_131.id, 'd', 1000.0, 0.0, vnd.id, 0.0, pid,
                    mdate, company.id, regime.id, 'none',
                ))
                line_rows.append((
                    mid, 20, acc_511.id, 'c', 0.0, 1000.0, vnd.id, 0.0, None,
                    mdate, company.id, regime.id, 'none',
                ))
            else:
                line_rows.append((
                    mid, 10, acc_111.id, 'd', 1000.0, 0.0, vnd.id, 0.0, None,
                    mdate, company.id, regime.id, 'none',
                ))
                line_rows.append((
                    mid, 20, acc_411.id, 'c', 0.0, 1000.0, vnd.id, 0.0, None,
                    mdate, company.id, regime.id, 'none',
                ))
        for i in range(0, len(line_rows), 5000):
            cr.executemany(
                """
                INSERT INTO vas_move_line
                    (move_id, sequence, account_id, name, debit, credit,
                     currency_id, amount_currency, partner_id, date,
                     company_id, regime_id, tax_status, direct_industry_status,
                     create_uid, write_uid, create_date, write_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'none',1,1,NOW(),NOW())
                """,
                line_rows[i:i + 5000],
            )
        cr.execute(
            'SELECT COUNT(*) FROM vas_move_line WHERE company_id = %s',
            [company.id],
        )
        n_lines = cr.fetchone()[0]
        self.assertEqual(n_lines, 300_000)
        print('BENCH_SEED done lines=%s in %.2fs' % (
            n_lines, time.perf_counter() - t_seed0,
        ))

        def generate_counted():
            self.env.flush_all()
            with VasQueryCounter(cr) as qc:
                snap = self.env['vas.report.snapshot'].generate_b01a(
                    company, periods[0], periods[-1], hide_reversed=True,
                )
                self.env.flush_all()
            return qc.count, snap

        # Warm-up ngoài phạm vi đếm
        generate_counted()
        counts = []
        times = []
        snap = None
        for _i in range(3):
            t0 = time.perf_counter()
            q, snap = generate_counted()
            times.append(time.perf_counter() - t0)
            counts.append(q)
        print('BENCH_GENERATE_3RUNS queries=%s times=%s' % (counts, times))
        self.assertEqual(counts[0], counts[1], counts)
        self.assertEqual(counts[1], counts[2], counts)
        q_gen = counts[0]
        t_gen = sum(times) / 3.0

        self.env.flush_all()
        t1 = time.perf_counter()
        data = snap.get_report_data()
        t_open = time.perf_counter() - t1
        print('BENCH_GENERATE seconds=%.3f queries=%s' % (t_gen, q_gen))
        print('BENCH_REOPEN seconds=%.3f lines=%s' % (t_open, len(data['lines'])))
        self.assertTrue(data['meta'].get('from_snapshot'))
        self.assertLess(q_gen, 80, 'Quá nhiều query khi lập (sau ghi lô): %s' % q_gen)
        print('BENCH_CLEANUP=TransactionCase_rollback')
