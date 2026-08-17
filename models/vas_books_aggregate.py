# -*- coding: utf-8 -*-
"""Gom số dư / PS / cặp đối ứng — dùng chung B01a / B02 / B09.

- 3 ``read_group`` số dư/PS (không đổi).
- **Thêm đúng 1** câu SQL gom cặp đối ứng (cố định — không tăng theo chỉ tiêu).

Ghép cặp 1↔N / N↔1 theo **cùng công thức** ``vas.account.ledger._split_counterparts``
(tỷ lệ + phần dư dòng đối ứng cuối, sắp theo mã TK rồi id dòng). Chứng từ
nhiều Nợ × nhiều Có: **không ghép**, trả cảnh báo.
"""
from collections import defaultdict

from odoo import models
from odoo.tools import SQL
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class VasBooksAggregate(models.AbstractModel):
    """Một lần quét sổ → dict bucket theo (account_id, partner_id).

    B01a / B02 / B09 sau này cùng gọi ``_books_aggregate_buckets`` — không mỗi
    mẫu một lượt quét riêng.
    """

    _name = 'vas.books.aggregate'
    _description = 'VAS books one-pass aggregate'

    def _books_aggregate_buckets(
        self, company, date_from, date_to, hide_reversed=True,
    ):
        """Trả ``{(account_id, partner_id_or_False): bucket_dict}``.

        bucket_dict keys: opening, opening_debit, opening_credit,
        ps_debit, ps_credit, closing, closing_debit, closing_credit.

        Đúng **3** ``read_group`` (đầu kỳ trước mốc, opening trong kỳ, PS trong kỳ)
        — không tăng theo số chỉ tiêu / số đối tác.
        """
        company.ensure_one()
        Line = self.env['vas.move.line']
        base = [('company_id', '=', company.id)]
        if hide_reversed:
            base += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            base.append(('move_id.state', 'in', ('posted', 'reversed')))

        # (account_id, partner_id) → net opening accumulator / ps
        opening_net = defaultdict(float)
        ps_debit = defaultdict(float)
        ps_credit = defaultdict(float)

        def _key(account_id, partner_id):
            return (account_id, partner_id or False)

        # 1) PS trước date_from → góp vào SD đầu
        for row in Line.read_group(
            base + [('date', '<', date_from)],
            ['debit:sum', 'credit:sum', 'account_id', 'partner_id'],
            ['account_id', 'partner_id'],
            lazy=False,
        ):
            acc = row['account_id'][0] if row.get('account_id') else False
            if not acc:
                continue
            partner = row['partner_id'][0] if row.get('partner_id') else False
            deb = row.get('debit') or 0.0
            cre = row.get('credit') or 0.0
            opening_net[_key(acc, partner)] += deb - cre

        # 2) move_kind=opening trong khoảng → góp vào SD đầu
        for row in Line.read_group(
            base + [
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('move_id.move_kind', '=', 'opening'),
            ],
            ['debit:sum', 'credit:sum', 'account_id', 'partner_id'],
            ['account_id', 'partner_id'],
            lazy=False,
        ):
            acc = row['account_id'][0] if row.get('account_id') else False
            if not acc:
                continue
            partner = row['partner_id'][0] if row.get('partner_id') else False
            deb = row.get('debit') or 0.0
            cre = row.get('credit') or 0.0
            opening_net[_key(acc, partner)] += deb - cre

        # 3) PS trong kỳ (không gồm opening)
        for row in Line.read_group(
            base + [
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('move_id.move_kind', '!=', 'opening'),
            ],
            ['debit:sum', 'credit:sum', 'account_id', 'partner_id'],
            ['account_id', 'partner_id'],
            lazy=False,
        ):
            acc = row['account_id'][0] if row.get('account_id') else False
            if not acc:
                continue
            partner = row['partner_id'][0] if row.get('partner_id') else False
            key = _key(acc, partner)
            ps_debit[key] += row.get('debit') or 0.0
            ps_credit[key] += row.get('credit') or 0.0

        all_keys = set(opening_net) | set(ps_debit) | set(ps_credit)
        buckets = {}
        for key in all_keys:
            opn = float_round(opening_net.get(key, 0.0), 2)
            pd = float_round(ps_debit.get(key, 0.0), 2)
            pc = float_round(ps_credit.get(key, 0.0), 2)
            closing = float_round(opn + pd - pc, 2)
            open_dr, open_cr = self._books_balance_cols(opn)
            close_dr, close_cr = self._books_balance_cols(closing)
            buckets[key] = {
                'opening': opn,
                'opening_debit': open_dr,
                'opening_credit': open_cr,
                'ps_debit': pd,
                'ps_credit': pc,
                'closing': closing,
                'closing_debit': close_dr,
                'closing_credit': close_cr,
            }
        return buckets

    def _books_balance_cols(self, balance):
        bal = float_round(balance, precision_digits=2)
        if float_compare(bal, 0.0, 2) > 0:
            return bal, 0.0
        if float_compare(bal, 0.0, 2) < 0:
            return 0.0, abs(bal)
        return 0.0, 0.0

    def _books_rollup_account(self, buckets, account_id):
        """Gộp mọi đối tác của một TK → một bucket (PARTNER_ALL)."""
        opn = pd = pc = 0.0
        for (acc, _pid), b in buckets.items():
            if acc != account_id:
                continue
            opn = float_round(opn + b['opening'], 2)
            pd = float_round(pd + b['ps_debit'], 2)
            pc = float_round(pc + b['ps_credit'], 2)
        closing = float_round(opn + pd - pc, 2)
        open_dr, open_cr = self._books_balance_cols(opn)
        close_dr, close_cr = self._books_balance_cols(closing)
        return {
            'opening': opn,
            'opening_debit': open_dr,
            'opening_credit': open_cr,
            'ps_debit': pd,
            'ps_credit': pc,
            'closing': closing,
            'closing_debit': close_dr,
            'closing_credit': close_cr,
        }

    # ------------------------------------------------------------------
    # Phát sinh đối ứng — đúng 1 câu SQL cố định
    # ------------------------------------------------------------------

    def _books_period_move_domain(
        self, company, date_from, date_to, hide_reversed=True,
    ):
        """Domain ``vas.move`` kỳ PS (không opening) — luôn gắn ``domain_for_amounts``."""
        company.ensure_one()
        Move = self.env['vas.move']
        domain = [
            ('company_id', '=', company.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_kind', '!=', 'opening'),
        ]
        if hide_reversed:
            domain += Move.domain_for_amounts()
        else:
            domain.append(('state', 'in', ('posted', 'reversed')))
        return domain

    def _books_counterpart_pairs(
        self, company, date_from, date_to, hide_reversed=True,
    ):
        """Một câu SQL → cặp PS đối ứng + cảnh báo chứng từ N×N.

        Trả dict::

            {
              'pairs': {(src_acc_id, src_side, opp_acc_id, opp_side): amount},
              'ambiguous_moves': [
                  {'move_id', 'name', 'amount', 'n_debit', 'n_credit'}, ...
              ],
            }

        ``src_side`` / ``opp_side`` ∈ ``{'debit', 'credit'}``.

        Công thức phân bổ = ``_split_counterparts`` (tỷ lệ theo tổng vế đối,
        phần dư dòng cuối sắp ``acc_code, line_id``). Nhiều Nợ × nhiều Có:
        không vào ``pairs``, chỉ ``ambiguous_moves``.
        """
        company.ensure_one()
        self.env.flush_all()
        Move = self.env['vas.move'].sudo()
        domain = self._books_period_move_domain(
            company, date_from, date_to, hide_reversed=hide_reversed,
        )
        move_query = Move._search(domain, bypass_access=True)
        move_sub = move_query.subselect()

        # Một execute — DB gom; không kéo dòng lên ghép bằng Python.
        self.env.cr.execute(SQL(
            """
            WITH filtered_moves AS (
                SELECT id FROM %(move_sub)s AS mq
            ),
            lines AS (
                SELECT
                    l.move_id,
                    l.id AS line_id,
                    l.account_id,
                    a.code AS acc_code,
                    l.debit,
                    l.credit
                FROM vas_move_line l
                JOIN filtered_moves fm ON fm.id = l.move_id
                JOIN vas_account a ON a.id = l.account_id
            ),
            shape AS (
                SELECT
                    move_id,
                    COUNT(*) FILTER (WHERE debit > 0) AS n_dr,
                    COUNT(*) FILTER (WHERE credit > 0) AS n_cr,
                    COALESCE(SUM(debit), 0) AS tot_dr,
                    COALESCE(SUM(credit), 0) AS tot_cr
                FROM lines
                GROUP BY move_id
            ),
            pairable AS (
                SELECT *
                  FROM shape
                 WHERE n_dr >= 1 AND n_cr >= 1
                   AND NOT (n_dr > 1 AND n_cr > 1)
            ),
            ambiguous AS (
                SELECT
                    s.move_id,
                    m.name AS move_name,
                    s.tot_dr AS amount,
                    s.n_dr,
                    s.n_cr
                  FROM shape s
                  JOIN vas_move m ON m.id = s.move_id
                 WHERE s.n_dr > 1 AND s.n_cr > 1
            ),
            dr_lines AS (
                SELECT move_id, account_id, line_id, debit AS amt, acc_code
                  FROM lines
                 WHERE debit > 0
                   AND move_id IN (SELECT move_id FROM pairable)
            ),
            cr_lines AS (
                SELECT move_id, account_id, line_id, credit AS amt, acc_code
                  FROM lines
                 WHERE credit > 0
                   AND move_id IN (SELECT move_id FROM pairable)
            ),
            src_dr AS (
                SELECT move_id, account_id, SUM(amt) AS amount_x
                  FROM dr_lines
                 GROUP BY move_id, account_id
            ),
            src_cr AS (
                SELECT move_id, account_id, SUM(amt) AS amount_x
                  FROM cr_lines
                 GROUP BY move_id, account_id
            ),
            -- Nguồn Nợ → đối ứng Có (cùng _split_counterparts khi target bên Nợ)
            ranked_dr AS (
                SELECT
                    s.move_id,
                    s.account_id AS src_account_id,
                    c.account_id AS opp_account_id,
                    s.amount_x,
                    ROUND(
                        (s.amount_x * c.amt / NULLIF(p.tot_cr, 0))::numeric, 2
                    ) AS provisional,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.move_id, s.account_id
                        ORDER BY c.acc_code, c.line_id
                    ) AS rn,
                    COUNT(*) OVER (
                        PARTITION BY s.move_id, s.account_id
                    ) AS n_opp
                  FROM src_dr s
                  JOIN cr_lines c ON c.move_id = s.move_id
                  JOIN pairable p ON p.move_id = s.move_id
            ),
            alloc_dr AS (
                SELECT
                    move_id, src_account_id, opp_account_id, amount_x,
                    rn, n_opp, provisional,
                    SUM(provisional) OVER (
                        PARTITION BY move_id, src_account_id
                        ORDER BY rn
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS run_sum
                  FROM ranked_dr
            ),
            share_dr AS (
                SELECT
                    src_account_id,
                    'debit'::text AS src_side,
                    opp_account_id,
                    'credit'::text AS opp_side,
                    CASE
                        WHEN rn = n_opp THEN
                            ROUND((amount_x - (run_sum - provisional))::numeric, 2)
                        ELSE provisional
                    END AS share
                  FROM alloc_dr
            ),
            -- Nguồn Có → đối ứng Nợ
            ranked_cr AS (
                SELECT
                    s.move_id,
                    s.account_id AS src_account_id,
                    d.account_id AS opp_account_id,
                    s.amount_x,
                    ROUND(
                        (s.amount_x * d.amt / NULLIF(p.tot_dr, 0))::numeric, 2
                    ) AS provisional,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.move_id, s.account_id
                        ORDER BY d.acc_code, d.line_id
                    ) AS rn,
                    COUNT(*) OVER (
                        PARTITION BY s.move_id, s.account_id
                    ) AS n_opp
                  FROM src_cr s
                  JOIN dr_lines d ON d.move_id = s.move_id
                  JOIN pairable p ON p.move_id = s.move_id
            ),
            alloc_cr AS (
                SELECT
                    move_id, src_account_id, opp_account_id, amount_x,
                    rn, n_opp, provisional,
                    SUM(provisional) OVER (
                        PARTITION BY move_id, src_account_id
                        ORDER BY rn
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS run_sum
                  FROM ranked_cr
            ),
            share_cr AS (
                SELECT
                    src_account_id,
                    'credit'::text AS src_side,
                    opp_account_id,
                    'debit'::text AS opp_side,
                    CASE
                        WHEN rn = n_opp THEN
                            ROUND((amount_x - (run_sum - provisional))::numeric, 2)
                        ELSE provisional
                    END AS share
                  FROM alloc_cr
            ),
            all_shares AS (
                SELECT * FROM share_dr
                UNION ALL
                SELECT * FROM share_cr
            )
            SELECT
                'pair'::text AS row_kind,
                src_account_id,
                src_side,
                opp_account_id,
                opp_side,
                SUM(share) AS amount,
                NULL::integer AS move_id,
                NULL::varchar AS move_name,
                NULL::integer AS n_dr,
                NULL::integer AS n_cr
              FROM all_shares
             GROUP BY src_account_id, src_side, opp_account_id, opp_side
            UNION ALL
            SELECT
                'ambiguous'::text,
                NULL, NULL, NULL, NULL,
                amount,
                move_id,
                move_name,
                n_dr,
                n_cr
              FROM ambiguous
            """,
            move_sub=move_sub,
        ))

        pairs = {}
        ambiguous_moves = []
        for row in self.env.cr.fetchall():
            kind = row[0]
            if kind == 'pair':
                src_id, src_side, opp_id, opp_side, amount = (
                    row[1], row[2], row[3], row[4], row[5] or 0.0,
                )
                if not src_id or not opp_id:
                    continue
                if float_is_zero(amount, 2):
                    continue
                key = (src_id, src_side, opp_id, opp_side)
                pairs[key] = float_round(
                    pairs.get(key, 0.0) + float(amount), 2,
                )
            else:
                ambiguous_moves.append({
                    'move_id': row[6],
                    'name': row[7] or '',
                    'amount': float_round(float(row[5] or 0.0), 2),
                    'n_debit': row[8] or 0,
                    'n_credit': row[9] or 0,
                })
        return {
            'pairs': pairs,
            'ambiguous_moves': ambiguous_moves,
        }

    def _books_counterpart_lookup(
        self, pairs, src_account_ids, src_side, opp_account_ids, opp_side,
    ):
        """Cộng PS đối ứng từ dict ``pairs`` (không thêm câu SQL)."""
        total = 0.0
        for sid in src_account_ids:
            for oid in opp_account_ids:
                total += pairs.get((sid, src_side, oid, opp_side), 0.0)
        return float_round(total, 2)

    def _books_counterpart_amounts_for_specs(
        self, company, date_from, date_to, specs, hide_reversed=True,
    ):
        """Một lần gom cặp + tra cứu theo danh sách spec chỉ tiêu.

        ``specs``: iterable ``(key, src_ids, src_side, opp_ids, opp_side)``.
        Số câu SQL **không** phụ thuộc ``len(specs)``.
        """
        result = self._books_counterpart_pairs(
            company, date_from, date_to, hide_reversed=hide_reversed,
        )
        amounts = {}
        for key, src_ids, src_side, opp_ids, opp_side in specs:
            amounts[key] = self._books_counterpart_lookup(
                result['pairs'], src_ids, src_side, opp_ids, opp_side,
            )
        return amounts, result['ambiguous_moves']

    def _books_move_shape_counts(
        self, company, date_from=None, date_to=None, hide_reversed=True,
    ):
        """Đếm chứng từ theo hình dạng chân (1×1, 1×N, N×1, N×N).

        Một câu SQL. Domain move = ``domain_for_amounts`` (+ company; tùy ngày).
        """
        company.ensure_one()
        self.env.flush_all()
        Move = self.env['vas.move'].sudo()
        domain = [('company_id', '=', company.id)]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if hide_reversed:
            domain += Move.domain_for_amounts()
        else:
            domain.append(('state', 'in', ('posted', 'reversed')))
        move_query = Move._search(domain, bypass_access=True)
        move_sub = move_query.subselect()
        self.env.cr.execute(SQL(
            """
            WITH filtered_moves AS (
                SELECT id FROM %(move_sub)s AS mq
            ),
            shape AS (
                SELECT
                    l.move_id,
                    COUNT(*) FILTER (WHERE l.debit > 0) AS n_dr,
                    COUNT(*) FILTER (WHERE l.credit > 0) AS n_cr
                  FROM vas_move_line l
                  JOIN filtered_moves fm ON fm.id = l.move_id
                 GROUP BY l.move_id
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE n_dr = 1 AND n_cr = 1
                ) AS one_one,
                COUNT(*) FILTER (
                    WHERE n_dr = 1 AND n_cr > 1
                ) AS one_many,
                COUNT(*) FILTER (
                    WHERE n_dr > 1 AND n_cr = 1
                ) AS many_one,
                COUNT(*) FILTER (
                    WHERE n_dr > 1 AND n_cr > 1
                ) AS many_many,
                COUNT(*) AS total
              FROM shape
            """,
            move_sub=move_sub,
        ))
        row = self.env.cr.fetchone() or (0, 0, 0, 0, 0)
        return {
            'one_one': row[0] or 0,
            'one_many': row[1] or 0,
            'many_one': row[2] or 0,
            'many_many': row[3] or 0,
            'total': row[4] or 0,
        }
