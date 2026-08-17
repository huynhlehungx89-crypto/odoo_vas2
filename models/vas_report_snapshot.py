# -*- coding: utf-8 -*-
"""Bản BCTC đã lập — lưu số + chi tiết; mở lại không tính lại từ sổ."""
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_round

from odoo.addons.connecta_vas.models.vas_b09_entry import B09_ENTRY_CODES
from odoo.addons.connecta_vas.models.vas_b09_meta import B09_DETAIL_SUM_CHECKS
from odoo.addons.connecta_vas.models.vas_report_line import (
    B09_FILL_KIND_SELECTION,
    B09_TABLE_STATUS_SELECTION,
)

B09_VALUE_SOURCE_SELECTION = [
    ('machine_ledger', 'Máy — từ sổ'),
    ('machine_report', 'Máy — từ B01a/B02'),
    ('machine_text', 'Máy — text hệ thống'),
    ('user', 'Người khai'),
    ('suggestion', 'Gợi ý máy (chưa xác nhận)'),
    ('copied_prior', 'Chép năm trước (chưa rà)'),
    ('empty', 'Trống'),
    ('section', 'Mục khung'),
]


class VasReportSnapshot(models.Model):
    _name = 'vas.report.snapshot'
    _description = 'Bản báo cáo tài chính đã lập'
    _order = 'date_computed desc, id desc'
    _inherit = ['vas.books.aggregate']

    name = fields.Char(string='Tên', required=True, default='/')
    form_code = fields.Char(string='Mẫu', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='cascade',
    )
    regime_id = fields.Many2one(
        related='company_id.vas_regime_id', store=True, readonly=True,
    )
    period_from_id = fields.Many2one(
        'vas.period', string='Từ kỳ', required=True, ondelete='restrict',
    )
    period_to_id = fields.Many2one(
        'vas.period', string='Đến kỳ', required=True, ondelete='restrict',
    )
    date_computed = fields.Datetime(
        string='Thời điểm lập', required=True, readonly=True, index=True,
        copy=False,
    )
    user_id = fields.Many2one(
        'res.users', string='Người lập', required=True, readonly=True,
        default=lambda self: self.env.user, copy=False,
    )
    hide_reversed = fields.Boolean(string='Ẩn đã đảo/điều chỉnh', default=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.ref('base.VND'), required=True,
    )
    warning_text = fields.Text(string='Cảnh báo lúc lập', readonly=True, copy=False)
    warning_level = fields.Selection(
        selection=[
            ('warning', 'Cảnh báo'),
            ('danger', 'Nguy hiểm'),
        ],
        string='Mức cảnh báo lúc lập',
        readonly=True,
        copy=False,
    )
    is_submitted = fields.Boolean(
        string='Đã nộp',
        default=False,
        copy=False,
        index=True,
        help='Bản đã nộp cấm sửa / xóa. Muốn khai lại → lập bản mới.',
    )
    line_ids = fields.One2many(
        'vas.report.snapshot.line', 'snapshot_id', string='Chỉ tiêu', copy=False,
    )
    ledger_changed = fields.Boolean(
        string='Sổ đã đổi sau khi lập',
        compute='_compute_ledger_changed',
    )
    ledger_stale_message = fields.Text(
        string='Cảnh báo sổ cũ',
        compute='_compute_ledger_changed',
    )
    imbalance_200_500 = fields.Float(string='Lệch 200−500', readonly=True, copy=False)
    check_60_4212_diff = fields.Float(
        string='Lệch mã 60 − KC 4212', readonly=True, copy=False,
    )
    check_60_b01a_417_diff = fields.Float(
        string='Lệch mã 60 − biến động B01a 417', readonly=True, copy=False,
    )
    check_b03_l1_diff = fields.Float(
        string='Lệch B03 70 − B01a 110 cuối', readonly=True, copy=False,
    )
    check_b03_l2_diff = fields.Float(
        string='Lệch B03 60 − B01a 110 đầu', readonly=True, copy=False,
    )
    check_b03_l4_diff = fields.Float(
        string='Lệch B03 L4 (quỹ − 50−61)', readonly=True, copy=False,
    )
    meta_json = fields.Text(
        string='Meta lúc lập (JSON)',
        readonly=True,
        copy=False,
        help='missing_accounts, total_na_children — lưu kèm để mở lại không tính.',
    )

    # -------------------------------------------------------------------------
    # Stale ledger (không tính lại số báo cáo)
    # -------------------------------------------------------------------------

    def _compute_ledger_changed(self):
        Move = self.env['vas.move']
        for snap in self:
            if not snap.date_computed or not snap.period_to_id:
                snap.ledger_changed = False
                snap.ledger_stale_message = False
                continue
            date_to = snap.period_to_id.date_end
            domain = [
                ('company_id', '=', snap.company_id.id),
                ('date', '<=', date_to),
                '|',
                ('create_date', '>', snap.date_computed),
                ('write_date', '>', snap.date_computed),
            ]
            changed = Move.search_count(domain)
            snap.ledger_changed = bool(changed)
            if changed:
                snap.ledger_stale_message = _(
                    'Bản lập lúc %(when)s có thể đã cũ: sau thời điểm đó, trong '
                    'phạm vi ảnh hưởng kỳ báo cáo (đến %(to)s) có %(n)s chứng từ '
                    'VAS được tạo / sửa / đảo. Số trên bản này KHÔNG đổi — '
                    'bấm «Lập lại» nếu cần bản mới.',
                    when=fields.Datetime.to_string(snap.date_computed),
                    to=date_to,
                    n=changed,
                )
            else:
                snap.ledger_stale_message = False

    # -------------------------------------------------------------------------
    # Submitted lock (model layer)
    # -------------------------------------------------------------------------

    def write(self, vals):
        if any(r.is_submitted for r in self):
            raise UserError(_(
                'Bản báo cáo đã nộp — không được sửa. Lập bản mới nếu cần khai lại.'
            ))
        return super().write(vals)

    def unlink(self):
        if any(r.is_submitted for r in self):
            raise UserError(_(
                'Bản báo cáo đã nộp — không được xóa.'
            ))
        # Xóa cả bản: gỡ dòng/chi tiết với cờ purge rồi mới super.
        details = self.mapped('line_ids.detail_ids')
        lines = self.mapped('line_ids')
        details.with_context(_vas_snapshot_purge=True).unlink()
        lines.with_context(_vas_snapshot_purge=True).unlink()
        return super().unlink()

    def action_open_view(self):
        """Màn hình XEM — khung OWL dùng chung (không form Odoo)."""
        self.ensure_one()
        return self.env['vas.report.engine'].action_open_fs_client(self)

    def get_formview_action(self, access_uid=None):
        """Click dòng trên list «bản đã lập» → tờ xem OWL, không form dữ liệu.

        Form nội bộ (dò lỗi) chỉ khi context ``vas_open_snapshot_form``.
        """
        self.ensure_one()
        if self.env.context.get('vas_open_snapshot_form'):
            return super().get_formview_action(access_uid=access_uid)
        return self.action_open_view()

    def action_mark_submitted(self):
        for rec in self:
            if rec.is_submitted:
                continue
            # Ghi trực tiếp super trước khi cờ khóa bật
            super(VasReportSnapshot, rec).write({'is_submitted': True})
        return True

    def action_regenerate(self):
        """Lập bản MỚI cùng tham số — bản cũ giữ nguyên."""
        self.ensure_one()
        if self.form_code == 'B02-DNN':
            new = self.generate_b02(
                self.company_id,
                self.period_from_id,
                self.period_to_id,
                hide_reversed=self.hide_reversed,
            )
        elif self.form_code == 'B03-DNN':
            new = self.generate_b03(
                self.company_id,
                self.period_from_id,
                self.period_to_id,
                hide_reversed=self.hide_reversed,
            )
        elif self.form_code == 'B09-DNN':
            new = self.generate_b09(
                self.company_id,
                self.period_from_id,
                self.period_to_id,
                hide_reversed=self.hide_reversed,
            )
        else:
            new = self.generate_b01a(
                self.company_id,
                self.period_from_id,
                self.period_to_id,
                hide_reversed=self.hide_reversed,
            )
        return self.env['vas.report.engine'].action_open_fs_client(new)

    # -------------------------------------------------------------------------
    # Generate B01a (one-pass aggregate → store)
    # -------------------------------------------------------------------------

    @api.model
    def generate_b01a(self, company, period_from, period_to, hide_reversed=True):
        """Tính một lần từ sổ (gom 3 read_group) rồi LƯU — không để wizard giữ số."""
        if not company.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if period_from.date_start > period_to.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (period_from, period_to):
            if p.fiscalyear_id.company_id != company:
                raise UserError(_(
                    'Kỳ %(p)s không thuộc công ty đang chọn.',
                    p=p.display_name,
                ))

        now = fields.Datetime.now()
        snap = self.create({
            'name': _('B01a %(a)s → %(b)s') % {
                'a': period_from.name, 'b': period_to.name,
            },
            'form_code': 'B01a-DNN',
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'date_computed': now,
            'user_id': self.env.user.id,
            'hide_reversed': hide_reversed,
            'currency_id': company.currency_id.id or self.env.ref('base.VND').id,
        })
        snap._store_b01a_from_ledger()
        return snap

    def _store_b01a_from_ledger(self):
        """Quét sổ một lượt → ghi line + detail + warning vào bản ghi."""
        self.ensure_one()
        if self.is_submitted:
            raise UserError(_('Bản đã nộp — không tính lại vào bản này.'))

        date_from = self.period_from_id.date_start
        date_to = self.period_to_id.date_end
        buckets = self._books_aggregate_buckets(
            self.company_id, date_from, date_to, self.hide_reversed,
        )
        Account = self.env['vas.account']
        ReportLine = self.env['vas.report.line']
        lines_def = ReportLine.search([
            ('form_code', '=', 'B01a-DNN'),
            ('regime_id', '=', self.regime_id.id),
            ('active', '=', True),
        ])

        # Prefetch accounts by code
        all_codes = set()
        for rl in lines_def:
            all_codes.update(ReportLine._parse_codes(rl.account_codes))
            all_codes.update(ReportLine._parse_codes(rl.warn_account_codes))
        acc_by_code = {
            a.code: a for a in Account.search([
                ('regime_id', '=', self.regime_id.id),
                ('code', 'in', list(all_codes)),
            ])
        }

        cache = {}
        missing_map = {}
        total_na_map = {}
        opposite_msgs = []
        orphan_msgs = []
        class_warnings = []
        detail_plan = {}  # report_line.id -> list of detail vals (without snapshot_line)

        def resolve_accounts(codes):
            found = Account.browse()
            missing = []
            for code in codes:
                acc = acc_by_code.get(code)
                if acc:
                    found |= acc
                else:
                    missing.append(code)
            return found, missing

        def side_from_bucket(bucket, side, which):
            net = bucket['opening' if which == 'opening' else 'closing']
            deb = bucket['opening_debit' if which == 'opening' else 'closing_debit']
            cre = bucket['opening_credit' if which == 'opening' else 'closing_credit']
            if side == 'debit':
                return deb, net, deb, cre
            if side == 'credit':
                return cre, net, deb, cre
            if side == 'signed_credit':
                return -net, net, deb, cre
            if side == 'signed_debit':
                return net, net, deb, cre
            return 0.0, net, deb, cre

        def eval_warnings(rl):
            msgs = []
            if rl.warn_kind == 'none':
                return msgs
            if rl.warn_kind == 'balance_on_codes':
                codes = ReportLine._parse_codes(rl.warn_account_codes)
                for code in codes:
                    acc = acc_by_code.get(code)
                    if not acc:
                        continue
                    row = self._books_rollup_account(buckets, acc.id)
                    if float_is_zero(row['closing'], 2) and float_is_zero(row['opening'], 2):
                        continue
                    related = self._related_codes_for_parent(acc, lines_def, acc_by_code)
                    detail = _(
                        'TK %(acc)s còn SD đầu %(o)s / cuối %(c)s.',
                        acc=acc.code,
                        o='{:,.0f}'.format(row['opening']),
                        c='{:,.0f}'.format(row['closing']),
                    )
                    if related:
                        detail = _(
                            '%(detail)s Thuộc chỉ tiêu: %(lines)s — cần phân loại tay '
                            '(không tự gắn TK cha dùng chung nhiều chỉ tiêu).',
                            detail=detail,
                            lines=', '.join(related),
                        )
                    if rl.warn_message:
                        msgs.append('%s %s' % (rl.warn_message, detail))
                    else:
                        msgs.append(_(
                            'Chỉ tiêu %(code)s — %(detail)s',
                            code=rl.code, detail=detail,
                        ))
            elif rl.warn_kind == 'residual_413_vnd':
                currency = rl.force_zero_currency_id or self.env.ref('base.VND')
                if self.company_id.currency_id != currency:
                    return msgs
                acc = acc_by_code.get('413')
                if not acc:
                    return msgs
                row = self._books_rollup_account(buckets, acc.id)
                if float_is_zero(row['closing'], 2):
                    return msgs
                msgs.append(rl.warn_message or _(
                    'Chỉ tiêu 415: công ty dùng VND nhưng TK 413 còn số dư cuối kỳ '
                    '%(c)s (đánh giá lại chưa xả hết).',
                    c='{:,.0f}'.format(row['closing']),
                ))
            return msgs

        def compute_amount(rl, which):
            key = (rl.id, which)
            if key in cache:
                return cache[key]

            if rl.amount_source == 'force_zero':
                cache[key] = 0.0
                return 0.0

            if rl.amount_source == 'total':
                total = 0.0
                na_children = []
                for child in rl.child_line_ids.sorted(lambda c: (c.sequence, c.code)):
                    val = compute_amount(child, which)
                    if val is None:
                        na_children.append(child.code)
                        continue
                    total = float_round(total + val, 2)
                if na_children:
                    total_na_map[rl.code] = list(dict.fromkeys(
                        total_na_map.get(rl.code, []) + na_children
                    ))
                    cache[key] = None
                    return None
                cache[key] = total
                return total

            if rl.amount_source == 'turnover':
                raise UserError(_(
                    'Chỉ tiêu %(code)s khai số phát sinh — B01a chưa dùng loại này.',
                    code=rl.code,
                ))

            codes = ReportLine._parse_codes(rl.account_codes)
            if not codes:
                cache[key] = 0.0
                return 0.0
            accounts, missing = resolve_accounts(codes)
            if missing:
                missing_map.setdefault(rl.code, [])
                for m in missing:
                    if m not in missing_map[rl.code]:
                        missing_map[rl.code].append(m)
                cache[key] = None
                return None
            if not rl.balance_side:
                raise UserError(_(
                    'Chỉ tiêu %(code)s thiếu khai bên Nợ/Có.',
                    code=rl.code,
                ))

            total = 0.0
            details = detail_plan.setdefault(rl.id, [])
            by_partner = bool(rl.aggregate_by_partner)

            for account in accounts:
                if by_partner and account.reconcile:
                    # Theo từng đối tác có trong buckets
                    partner_keys = [
                        (acc, pid) for (acc, pid) in buckets if acc == account.id and pid
                    ]
                    for (_acc, pid) in partner_keys:
                        b = buckets[(_acc, pid)]
                        amt, _net, deb, cre = side_from_bucket(
                            b, rl.balance_side, which,
                        )
                        if which == 'closing':
                            # detail lưu cả opening+closing trên cùng bản ghi detail
                            pass
                        total = float_round(total + amt, 2)
                    # Orphan partner=False
                    orphan = buckets.get((account.id, False))
                    if orphan:
                        o_net = orphan['opening' if which == 'opening' else 'closing']
                        if not float_is_zero(o_net, 2):
                            col = _('cuối kỳ') if which == 'closing' else _('đầu năm')
                            side_lbl = _('Nợ') if float_round(o_net, 2) > 0 else _('Có')
                            orphan_msgs.append(_(
                                'Chỉ tiêu %(code)s: TK %(acc)s còn SD %(side)s %(amt)s '
                                '(%(col)s) trên dòng không có đối tác — không tự xếp '
                                'vào chỉ tiêu công nợ; cần gắn đối tác hoặc phân loại tay.',
                                code=rl.code,
                                acc=account.code,
                                side=side_lbl,
                                amt='{:,.0f}'.format(abs(o_net)),
                                col=col,
                            ))
                    # Chi tiết: chỉ ghi một lần khi which==closing
                    if which == 'closing':
                        for (_acc, pid) in partner_keys:
                            b = buckets[(_acc, pid)]
                            od = b['opening_debit'] if rl.balance_side == 'debit' else (
                                b['opening_credit'] if rl.balance_side == 'credit' else (
                                    -b['opening'] if rl.balance_side == 'signed_credit' else b['opening']
                                )
                            )
                            cd = b['closing_debit'] if rl.balance_side == 'debit' else (
                                b['closing_credit'] if rl.balance_side == 'credit' else (
                                    -b['closing'] if rl.balance_side == 'signed_credit' else b['closing']
                                )
                            )
                            if float_is_zero(od, 2) and float_is_zero(cd, 2):
                                continue
                            details.append({
                                'account_id': account.id,
                                'account_code': account.code,
                                'partner_id': pid,
                                'amount_opening': float_round(od, 2),
                                'amount_closing': float_round(cd, 2),
                            })
                    continue

                # PARTNER_ALL (không tách đối tác, hoặc TK không reconcile)
                b = self._books_rollup_account(buckets, account.id)
                amt, net, deb, cre = side_from_bucket(b, rl.balance_side, which)
                if (
                    not by_partner
                    and rl.balance_side in ('debit', 'credit')
                ):
                    opp = cre if rl.balance_side == 'debit' else deb
                    if not float_is_zero(opp, 2):
                        want = _('Nợ') if rl.balance_side == 'debit' else _('Có')
                        got = _('Có') if rl.balance_side == 'debit' else _('Nợ')
                        col = _('cuối kỳ') if which == 'closing' else _('đầu năm')
                        opposite_msgs.append(_(
                            'Chỉ tiêu %(code)s: Chỉ tiêu lấy SD %(want)s nhưng TK %(acc)s '
                            'đang dư %(got)s %(amt)s (%(col)s).',
                            code=rl.code,
                            want=want,
                            acc=account.code,
                            got=got,
                            amt='{:,.0f}'.format(opp),
                            col=col,
                        ))
                total = float_round(total + amt, 2)
                if which == 'closing':
                    od = b['opening_debit'] if rl.balance_side == 'debit' else (
                        b['opening_credit'] if rl.balance_side == 'credit' else (
                            -b['opening'] if rl.balance_side == 'signed_credit' else b['opening']
                        )
                    )
                    cd = b['closing_debit'] if rl.balance_side == 'debit' else (
                        b['closing_credit'] if rl.balance_side == 'credit' else (
                            -b['closing'] if rl.balance_side == 'signed_credit' else b['closing']
                        )
                    )
                    if not float_is_zero(od, 2) or not float_is_zero(cd, 2):
                        details.append({
                            'account_id': account.id,
                            'account_code': account.code,
                            'partner_id': False,
                            'amount_opening': float_round(od, 2),
                            'amount_closing': float_round(cd, 2),
                        })

            if rl.sign_negative:
                total = float_round(-total, 2)
            cache[key] = total
            return total

        for rl in lines_def:
            class_warnings.extend(eval_warnings(rl))

        line_vals = []
        for rl in lines_def.sorted(lambda r: (r.sequence, r.code)):
            opening = compute_amount(rl, 'opening')
            closing = compute_amount(rl, 'closing')
            # force sign_negative already applied in compute; details need flip too
            dets = detail_plan.get(rl.id, [])
            if rl.sign_negative:
                for d in dets:
                    d['amount_opening'] = float_round(-d['amount_opening'], 2)
                    d['amount_closing'] = float_round(-d['amount_closing'], 2)
            line_vals.append((rl, opening, closing, dets))

        by_code = {rl.code: closing for rl, _o, closing, _d in line_vals}
        assets = by_code.get('200')
        equity = by_code.get('500')
        imbalance = None
        if assets is not None and equity is not None:
            diff = float_round(assets - equity, 2)
            if not float_is_zero(diff, 2):
                imbalance = diff

        opposite_unique = list(dict.fromkeys(opposite_msgs))
        orphan_unique = list(dict.fromkeys(orphan_msgs))
        warning = self._build_warning_text(
            missing_map, total_na_map, class_warnings,
            opposite_unique, orphan_unique, imbalance,
        )
        warning_level = 'danger' if imbalance is not None else (
            'warning' if warning else False
        )

        # Persist lines + details — MỘT create theo lô (không 1 INSERT / chỉ tiêu)
        SnapLine = self.env['vas.report.snapshot.line']
        SnapDetail = self.env['vas.report.snapshot.detail']
        line_cmds = []
        detail_by_index = []
        for rl, opening, closing, dets in line_vals:
            line_cmds.append({
                'snapshot_id': self.id,
                'report_line_id': rl.id,
                'sequence': rl.sequence,
                'code': rl.code,
                'name': rl.name,
                'line_role': rl.line_role,
                'amount_opening': opening if opening is not None else 0.0,
                'amount_closing': closing if closing is not None else 0.0,
                'is_na_opening': opening is None,
                'is_na_closing': closing is None,
                'show_negative_paren': rl.show_negative_paren,
                'aggregate_by_partner': rl.aggregate_by_partner,
                'note_b09_code': rl.note_b09_code or False,
            })
            detail_by_index.append(dets or [])
        slines = SnapLine.create(line_cmds) if line_cmds else SnapLine.browse()
        detail_cmds = []
        for sline, dets in zip(slines, detail_by_index):
            for d in dets:
                detail_cmds.append(dict(d, snapshot_line_id=sline.id))
        if detail_cmds:
            SnapDetail.create(detail_cmds)

        self.write({
            'warning_text': warning or False,
            'warning_level': warning_level or False,
            'imbalance_200_500': imbalance if imbalance is not None else 0.0,
            'meta_json': json.dumps({
                'missing_accounts': missing_map,
                'total_na_children': total_na_map,
                'opposite_side_msgs': opposite_unique,
                'orphan_partner_msgs': orphan_unique,
            }, ensure_ascii=False),
        })
        return True

    # -------------------------------------------------------------------------
    # Generate B02 (KQKD) — PS trần / đối ứng / code_custom
    # -------------------------------------------------------------------------

    @api.model
    def generate_b02(self, company, period_from, period_to, hide_reversed=True):
        """Tính B02 một lần từ sổ (3 read_group + 1 cặp đối ứng) rồi LƯU."""
        if not company.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if period_from.date_start > period_to.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (period_from, period_to):
            if p.fiscalyear_id.company_id != company:
                raise UserError(_(
                    'Kỳ %(p)s không thuộc công ty đang chọn.',
                    p=p.display_name,
                ))

        now = fields.Datetime.now()
        snap = self.create({
            'name': _('B02 %(a)s → %(b)s') % {
                'a': period_from.name, 'b': period_to.name,
            },
            'form_code': 'B02-DNN',
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'date_computed': now,
            'user_id': self.env.user.id,
            'hide_reversed': hide_reversed,
            'currency_id': company.currency_id.id or self.env.ref('base.VND').id,
        })
        snap._store_b02_from_ledger()
        return snap

    def _b02_loan_interest_amount(self, company, date_from, date_to, hide_reversed, acc_635_ids):
        """PS Nợ 635 từ move_kind loan_interest / loan_interest_pay — một read_group."""
        if not acc_635_ids:
            return 0.0
        Line = self.env['vas.move.line']
        domain = [
            ('company_id', '=', company.id),
            ('account_id', 'in', list(acc_635_ids)),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.move_kind', 'in', ('loan_interest', 'loan_interest_pay')),
        ]
        if hide_reversed:
            domain += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            domain.append(('move_id.state', 'in', ('posted', 'reversed')))
        rows = Line.read_group(domain, ['debit:sum'], [], lazy=False)
        return float_round((rows[0].get('debit') if rows else 0.0) or 0.0, 2)

    def _store_b02_from_ledger(self):
        """Gom sổ cố định → ghi chỉ tiêu B02 (amount_closing = số kỳ này)."""
        self.ensure_one()
        if self.is_submitted:
            raise UserError(_('Bản đã nộp — không tính lại vào bản này.'))
        if self.form_code != 'B02-DNN':
            raise UserError(_('Chỉ dùng cho mẫu B02-DNN.'))

        date_from = self.period_from_id.date_start
        date_to = self.period_to_id.date_end
        company = self.company_id
        hide = self.hide_reversed

        buckets = self._books_aggregate_buckets(company, date_from, date_to, hide)
        cp = self._books_counterpart_pairs(company, date_from, date_to, hide)
        pairs = cp['pairs']
        ambiguous_moves = cp['ambiguous_moves']

        ReportLine = self.env['vas.report.line']
        lines_def = ReportLine.search([
            ('form_code', '=', 'B02-DNN'),
            ('regime_id', '=', company.vas_regime_id.id),
            ('active', '=', True),
        ], order='sequence, code, id')

        Account = self.env['vas.account']
        acc_by_code = {
            a.code: a for a in Account.search([
                ('regime_id', '=', company.vas_regime_id.id),
            ])
        }

        missing_map = {}
        total_na_map = {}
        not_closed_msgs = []
        residual_635_amt = 0.0
        orphan_msgs = []
        cache = {}

        def resolve_accounts(codes):
            found = Account.browse()
            missing = []
            for code in codes:
                acc = acc_by_code.get(code)
                if acc:
                    found |= acc
                else:
                    missing.append(code)
            return found, missing

        def gross_ps(acc_ids, side):
            total = 0.0
            for aid in acc_ids:
                row = self._books_rollup_account(buckets, aid)
                total += row['ps_credit' if side == 'credit' else 'ps_debit']
            return float_round(total, 2)

        def counterpart_amount(rl, src_ids, opp_ids):
            amt = self._books_counterpart_lookup(
                pairs, src_ids, rl.source_side, opp_ids, rl.counterpart_side,
            )
            if rl.counterpart_net_both_ways:
                # Chiều ngược (vd Nợ 821 ↔ Có 911) trừ đi
                rev = self._books_counterpart_lookup(
                    pairs, src_ids, rl.counterpart_side, opp_ids, rl.source_side,
                )
                amt = float_round(amt - rev, 2)
            return amt

        def compute_amount(rl):
            if rl.id in cache:
                return cache[rl.id]

            if rl.amount_source == 'force_zero':
                cache[rl.id] = 0.0
                return 0.0

            if rl.amount_source == 'total':
                total = 0.0
                na_children = []
                for child in rl.child_line_ids.sorted(lambda c: (c.sequence, c.code)):
                    val = compute_amount(child)
                    if val is None:
                        na_children.append(child.code)
                        continue
                    total = float_round(total + val, 2)
                if na_children:
                    total_na_map[rl.code] = list(dict.fromkeys(
                        total_na_map.get(rl.code, []) + na_children
                    ))
                    cache[rl.id] = None
                    return None
                cache[rl.id] = total
                return total

            if rl.amount_source == 'code_custom':
                if rl.code_custom_key == 'b02_loan_interest':
                    codes = ReportLine._parse_codes(rl.account_codes) or ['635']
                    accs, missing = resolve_accounts(codes)
                    if missing:
                        missing_map.setdefault(rl.code, [])
                        for m in missing:
                            if m not in missing_map[rl.code]:
                                missing_map[rl.code].append(m)
                    interest = self._b02_loan_interest_amount(
                        company, date_from, date_to, hide, accs.ids,
                    )
                    ps635 = gross_ps(accs.ids, 'debit')
                    residual = float_round(ps635 - interest, 2)
                    cache[rl.id] = interest
                    compute_amount._residual_635 = residual
                    return interest
                raise UserError(_(
                    'Chỉ tiêu %(code)s khai tính riêng bằng code nhưng thiếu '
                    'code_custom_key được hỗ trợ (có: b02_loan_interest).',
                    code=rl.code,
                ))

            if rl.amount_source != 'turnover':
                raise UserError(_(
                    'Chỉ tiêu B02 %(code)s: cách lấy số %(src)s không dùng trên B02.',
                    code=rl.code, src=rl.amount_source,
                ))

            codes = ReportLine._parse_codes(rl.account_codes)
            if not codes:
                cache[rl.id] = 0.0
                return 0.0
            accounts, missing = resolve_accounts(codes)
            if missing:
                missing_map.setdefault(rl.code, [])
                for m in missing:
                    if m not in missing_map[rl.code]:
                        missing_map[rl.code].append(m)
                if not accounts:
                    cache[rl.id] = None
                    return None

            src_ids = accounts.ids
            side = rl.source_side or 'credit'

            if rl.turnover_mode == 'gross':
                amt = gross_ps(src_ids, side)
            elif rl.turnover_mode == 'counterpart':
                opp_codes = ReportLine._parse_codes(rl.counterpart_account_codes)
                opp_accs, opp_missing = resolve_accounts(opp_codes)
                if opp_missing:
                    missing_map.setdefault(rl.code, [])
                    for m in opp_missing:
                        if m not in missing_map[rl.code]:
                            missing_map[rl.code].append(m)
                amt = counterpart_amount(rl, src_ids, opp_accs.ids)
                # Cảnh báo chưa KC: đối ứng 911 = 0 nhưng còn PS trên TK nguồn
                if '911' in (opp_codes or []):
                    ps_any = float_round(
                        gross_ps(src_ids, 'debit') + gross_ps(src_ids, 'credit'), 2,
                    )
                    if float_is_zero(amt, 2) and not float_is_zero(ps_any, 2):
                        not_closed_msgs.append(_(
                            'Chỉ tiêu %(code)s (%(name)s): đối ứng 911 = 0 nhưng '
                            'TK %(accs)s còn PS %(ps)s trong kỳ — có thể '
                            'chưa kết chuyển.',
                            code=rl.code,
                            name=rl.name,
                            accs=','.join(codes),
                            ps='{:,.0f}'.format(ps_any),
                        ))
            else:
                raise UserError(_(
                    'Chỉ tiêu %(code)s: thiếu turnover_mode (gross/counterpart).',
                    code=rl.code,
                ))

            if rl.sign_negative:
                amt = float_round(-amt, 2)
            cache[rl.id] = amt
            return amt

        compute_amount._residual_635 = 0.0

        line_vals = []
        for rl in lines_def:
            period_amt = compute_amount(rl)
            line_vals.append((rl, period_amt))

        residual_635_amt = float_round(compute_amount._residual_635, 2)

        # Orphan: TK lớp 5–8 có PS kỳ, không thuộc nguồn/đối ứng chỉ tiêu B02
        # (loại 911 — TK kết chuyển, không phải chỉ tiêu nguồn)
        covered = set()
        for rl in lines_def.filtered(lambda l: l.line_role == 'detail'):
            covered.update(ReportLine._parse_codes(rl.account_codes))
            covered.update(ReportLine._parse_codes(rl.counterpart_account_codes))
        covered.add('911')
        for code, acc in acc_by_code.items():
            if not code or code[0] not in '5678':
                continue
            if code in covered:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            ps = float_round(row['ps_debit'] + row['ps_credit'], 2)
            if float_is_zero(ps, 2):
                continue
            orphan_msgs.append(_(
                'TK %(code)s có PS kỳ %(ps)s nhưng không thuộc chỉ tiêu B02 nào.',
                code=code, ps='{:,.0f}'.format(ps),
            ))

        by_code = {
            rl.code: (amt if amt is not None else 0.0)
            for rl, amt in line_vals
        }
        code_60 = by_code.get('60', 0.0)

        # G2(a): mã 60 = net KC vào 4212
        acc_4212 = acc_by_code.get('4212')
        acc_911 = acc_by_code.get('911')
        kc_4212 = 0.0
        if acc_4212 and acc_911:
            profit = self._books_counterpart_lookup(
                pairs, [acc_4212.id], 'credit', [acc_911.id], 'debit',
            )
            loss = self._books_counterpart_lookup(
                pairs, [acc_4212.id], 'debit', [acc_911.id], 'credit',
            )
            kc_4212 = float_round(profit - loss, 2)
        diff_4212 = float_round(code_60 - kc_4212, 2)

        # G2(b): biến động B01a 417 (421+4211+4212, signed_credit)
        delta_417 = 0.0
        for code in ('421', '4211', '4212'):
            acc = acc_by_code.get(code)
            if not acc:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            # signed_credit amount = -net
            open_s = float_round(-row['opening'], 2)
            close_s = float_round(-row['closing'], 2)
            delta_417 = float_round(delta_417 + (close_s - open_s), 2)
        diff_417 = float_round(code_60 - delta_417, 2)

        warn_parts = []
        if missing_map:
            bits = [
                _('Thiếu TK %(codes)s (chỉ tiêu %(c)s)') % {
                    'codes': ','.join(v), 'c': k,
                }
                for k, v in sorted(missing_map.items())
            ]
            warn_parts.append(_('Thiếu tài khoản trên chart: %s.') % '; '.join(bits))
        if total_na_map:
            bits = [
                _('%(c)s thiếu con %(ch)s') % {'c': k, 'ch': ','.join(v)}
                for k, v in sorted(total_na_map.items())
            ]
            warn_parts.append(_('Tổng N/A: %s.') % '; '.join(bits))
        warn_parts.extend(not_closed_msgs)
        if not float_is_zero(residual_635_amt, 2):
            warn_parts.append(_(
                'Mã 23: PS Nợ 635 còn %(amt)s chưa phân loại được thành '
                'chi phí lãi vay (loan_interest / loan_interest_pay) — '
                'KHÔNG gộp vào mã 23.',
                amt='{:,.0f}'.format(residual_635_amt),
            ))
        warn_parts.extend(orphan_msgs)
        for amb in ambiguous_moves:
            warn_parts.append(_(
                'Chứng từ %(name)s: nhiều Nợ × nhiều Có (N=%(nd)s, C=%(nc)s), '
                'số %(amt)s không quy được về cặp đối ứng — không đoán.',
                name=amb.get('name') or amb.get('move_id'),
                nd=amb.get('n_debit'),
                nc=amb.get('n_credit'),
                amt='{:,.0f}'.format(amb.get('amount') or 0.0),
            ))
        danger = False
        if not float_is_zero(diff_4212, 2):
            danger = True
            warn_parts.append(_(
                'LƯỚI G2: mã 60 (%(a)s) lệch số KC vào 4212 (%(b)s) = %(d)s.',
                a='{:,.0f}'.format(code_60),
                b='{:,.0f}'.format(kc_4212),
                d='{:,.0f}'.format(diff_4212),
            ))
        if not float_is_zero(diff_417, 2):
            danger = True
            warn_parts.append(_(
                'LƯỚI G2: mã 60 (%(a)s) lệch biến động LN chưa phân phối B01a '
                '417 (%(b)s) = %(d)s.',
                a='{:,.0f}'.format(code_60),
                b='{:,.0f}'.format(delta_417),
                d='{:,.0f}'.format(diff_417),
            ))

        # Phương án tạm 31/32: PS trọn 711/811 — cảnh báo khi có phát sinh
        ps_other = 0.0
        for code in ('711', '811'):
            acc = acc_by_code.get(code)
            if not acc:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            ps_other = float_round(
                ps_other + row['ps_debit'] + row['ps_credit'], 2,
            )
        if not float_is_zero(ps_other, 2):
            warn_parts.append(_(
                'Mã 31 và 32 đang trình bày theo phương án tạm: lấy trọn phát sinh '
                '711 và 811 (đối ứng 911), không tách chênh lệch thanh lý/nhượng bán '
                'TSCĐ theo hướng dẫn TT133 — vì chưa có chức năng thanh lý/nhượng bán. '
                'Nếu trong số này có khoản TL/NB tài sản thì số đang là gộp, không phải '
                'số thuần theo hướng dẫn. Không chặn lập báo cáo.'
            ))

        warning = '\n'.join(warn_parts) if warn_parts else False
        warning_level = 'danger' if danger else ('warning' if warning else False)

        SnapLine = self.env['vas.report.snapshot.line']
        line_cmds = []
        for rl, period_amt in line_vals:
            line_cmds.append({
                'snapshot_id': self.id,
                'report_line_id': rl.id,
                'sequence': rl.sequence,
                'code': rl.code,
                'name': rl.name,
                'line_role': rl.line_role,
                'amount_opening': 0.0,
                'amount_closing': period_amt if period_amt is not None else 0.0,
                'is_na_opening': False,
                'is_na_closing': period_amt is None,
                'show_negative_paren': rl.show_negative_paren,
                'aggregate_by_partner': False,
                'note_b09_code': rl.note_b09_code or False,
            })
        if line_cmds:
            SnapLine.create(line_cmds)

        self.write({
            'warning_text': warning or False,
            'warning_level': warning_level or False,
            'check_60_4212_diff': diff_4212,
            'check_60_b01a_417_diff': diff_417,
            'meta_json': json.dumps({
                'missing_accounts': missing_map,
                'total_na_children': total_na_map,
                'not_closed_911': not_closed_msgs,
                'residual_635': residual_635_amt,
                'orphan_pl_accounts': orphan_msgs,
                'ambiguous_moves': ambiguous_moves,
                'kc_4212': kc_4212,
                'delta_b01a_417': delta_417,
                'code_60': code_60,
            }, ensure_ascii=False, default=str),
        })
        return True

    # -------------------------------------------------------------------------
    # Generate B03 — khung + 01/60/70 từ bản B01a/B02 đã lập
    # -------------------------------------------------------------------------

    @api.model
    def generate_b03(self, company, period_from, period_to, hide_reversed=True):
        """Lập B03 từ bản B01a+B02 đã lưu; không tự lập ngầm B01a/B02."""
        if not company.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if period_from.date_start > period_to.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (period_from, period_to):
            if p.fiscalyear_id.company_id != company:
                raise UserError(_(
                    'Kỳ %(p)s không thuộc công ty đang chọn.',
                    p=p.display_name,
                ))

        b01a = self._find_period_snapshot(
            'B01a-DNN', company, period_from, period_to,
        )
        b02 = self._find_period_snapshot(
            'B02-DNN', company, period_from, period_to,
        )
        missing = []
        if not b01a:
            missing.append(_('B01a-DNN'))
        if not b02:
            missing.append(_('B02-DNN'))
        if missing:
            raise UserError(_(
                'Chưa lập %(forms)s cho công ty «%(co)s» kỳ %(a)s → %(b)s. '
                'Phải lập các báo cáo đó trước — B03 không tự lập ngầm và '
                'không điền 0 thay thế (mã 01 lấy B02.50; mã 60/70 lấy B01a.110).',
                forms=', '.join(missing),
                co=company.display_name,
                a=period_from.name,
                b=period_to.name,
            ))

        now = fields.Datetime.now()
        snap = self.create({
            'name': _('B03 %(a)s → %(b)s') % {
                'a': period_from.name, 'b': period_to.name,
            },
            'form_code': 'B03-DNN',
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'date_computed': now,
            'user_id': self.env.user.id,
            'hide_reversed': hide_reversed,
            'currency_id': company.currency_id.id or self.env.ref('base.VND').id,
        })
        snap._store_b03_from_snapshots(b01a, b02)
        return snap

    def _store_b03_from_snapshots(self, b01a_snap, b02_snap):
        """Ghi chỉ tiêu B03: 01/60/70 từ snapshot; 03–08/10–14 từ sổ; tổng theo seed."""
        self.ensure_one()
        if self.is_submitted:
            raise UserError(_('Bản đã nộp — không tính lại vào bản này.'))
        if self.form_code != 'B03-DNN':
            raise UserError(_('Chỉ dùng cho mẫu B03-DNN.'))

        company = self.company_id
        date_from = self.period_from_id.date_start
        date_to = self.period_to_id.date_end
        hide = self.hide_reversed

        ReportLine = self.env['vas.report.line']
        lines_def = ReportLine.search([
            ('form_code', '=', 'B03-DNN'),
            ('regime_id', '=', company.vas_regime_id.id),
            ('active', '=', True),
        ], order='sequence, code, id')

        b01a_by = {l.code: l for l in b01a_snap.line_ids}
        b02_by = {l.code: l for l in b02_snap.line_ids}

        # Đúng 1 lần gom sổ + 1 lần đối ứng — không tăng theo số chỉ tiêu
        buckets = self._books_aggregate_buckets(company, date_from, date_to, hide)
        cp = self._books_counterpart_pairs(company, date_from, date_to, hide)
        pairs = cp['pairs']

        Account = self.env['vas.account']
        accounts = Account.search([('regime_id', '=', company.vas_regime_id.id)])
        acc_by_code = {a.code: a for a in accounts}
        ids_by_code = {a.code: a.id for a in accounts}

        warn_parts = []
        danger = False
        stage2, stage2_meta = self._b03_compute_stage2(
            company, buckets, pairs, acc_by_code, ids_by_code, b02_by, warn_parts,
            report_lines=lines_def,
            date_from=date_from,
            date_to=date_to,
            hide_reversed=hide,
        )
        stage3, stage3_meta = self._b03_compute_stage3(
            company, acc_by_code, warn_parts,
            date_from=date_from,
            date_to=date_to,
            hide_reversed=hide,
        )

        cache = {}
        total_na_map = {}

        def snap_amount(src_map, code, which):
            row = src_map.get(code)
            if not row:
                return None
            if which == 'opening':
                if row.is_na_opening:
                    return None
                return float_round(row.amount_opening, 2)
            if row.is_na_closing:
                return None
            return float_round(row.amount_closing, 2)

        def compute_amount(rl):
            if rl.id in cache:
                return cache[rl.id]

            if rl.amount_source == 'total':
                total = 0.0
                na_children = []
                for child in rl.child_line_ids.sorted(lambda c: (c.sequence, c.code)):
                    val = compute_amount(child)
                    if val is None:
                        na_children.append(child.code)
                        continue
                    total = float_round(total + val, 2)
                if na_children:
                    total_na_map[rl.code] = list(dict.fromkeys(
                        total_na_map.get(rl.code, []) + na_children
                    ))
                    cache[rl.id] = None
                    return None
                cache[rl.id] = total
                return total

            if rl.amount_source == 'code_custom':
                key = rl.code_custom_key or ''
                if key == 'b03_pending':
                    cache[rl.id] = 0.0
                    return 0.0
                if key == 'b03_from_b02:50':
                    amt = snap_amount(b02_by, '50', 'closing')
                    if amt is None:
                        raise UserError(_(
                            'Bản B02 cùng kỳ không có mã 50 (lợi nhuận trước thuế) '
                            'hợp lệ — không thể lập B03 mã 01. Không điền 0 thay thế.'
                        ))
                    cache[rl.id] = amt
                    return amt
                if key == 'b03_from_b01a:110:opening':
                    amt = snap_amount(b01a_by, '110', 'opening')
                    if amt is None:
                        raise UserError(_(
                            'Bản B01a cùng kỳ không có mã 110 đầu kỳ hợp lệ — '
                            'không thể lập B03 mã 60. Không điền 0 thay thế.'
                        ))
                    cache[rl.id] = amt
                    return amt
                if key == 'b03_from_b01a:110:closing':
                    amt = snap_amount(b01a_by, '110', 'closing')
                    if amt is None:
                        raise UserError(_(
                            'Bản B01a cùng kỳ không có mã 110 cuối kỳ hợp lệ — '
                            'không thể lập B03 mã 70. Không điền 0 thay thế.'
                        ))
                    cache[rl.id] = amt
                    return amt
                if key == 'b03_stage2':
                    if rl.code not in stage2:
                        raise UserError(_(
                            'Chỉ tiêu B03 %(code)s khai b03_stage2 nhưng chưa có công thức.',
                            code=rl.code,
                        ))
                    cache[rl.id] = stage2[rl.code]
                    return stage2[rl.code]
                if key == 'b03_stage3':
                    if rl.code not in stage3:
                        raise UserError(_(
                            'Chỉ tiêu B03 %(code)s khai b03_stage3 nhưng chưa có công thức.',
                            code=rl.code,
                        ))
                    cache[rl.id] = stage3[rl.code]
                    return stage3[rl.code]
                raise UserError(_(
                    'Chỉ tiêu B03 %(code)s: code_custom_key «%(key)s» chưa hỗ trợ.',
                    code=rl.code, key=key,
                ))

            raise UserError(_(
                'Chỉ tiêu B03 %(code)s: cách lấy số %(src)s không dùng trên B03.',
                code=rl.code, src=rl.amount_source,
            ))

        line_vals = []
        by_code_amt = {}
        for rl in lines_def:
            amt = compute_amount(rl)
            line_vals.append((rl, amt))
            by_code_amt[rl.code] = amt

        # Cảnh báo C1: dư 1281/1288
        for code in ('1281', '1288'):
            acc = acc_by_code.get(code)
            if not acc:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            if float_is_zero(row['closing'], 2) and float_is_zero(row['opening'], 2):
                continue
            warn_parts.append(_(
                '1281/1288 còn SD — không tự xếp vào TĐT (C1 / B03 60–70). '
                'TK %(acc)s còn SD đầu %(o)s / cuối %(c)s — cần phân loại tay.',
                acc=acc.code,
                o='{:,.0f}'.format(row['opening']),
                c='{:,.0f}'.format(row['closing']),
            ))

        # Lưới L1 / L2
        b01a_110 = b01a_by.get('110')
        b01a_o = (
            float_round(b01a_110.amount_opening, 2)
            if b01a_110 and not b01a_110.is_na_opening else None
        )
        b01a_c = (
            float_round(b01a_110.amount_closing, 2)
            if b01a_110 and not b01a_110.is_na_closing else None
        )
        amt_60 = by_code_amt.get('60')
        amt_70 = by_code_amt.get('70')
        diff_l2 = 0.0
        diff_l1 = 0.0
        if amt_60 is not None and b01a_o is not None:
            diff_l2 = float_round(amt_60 - b01a_o, 2)
            if not float_is_zero(diff_l2, 2):
                danger = True
                warn_parts.append(_(
                    'LƯỚI L2: B03 mã 60 (%(a)s) lệch B01a 110 đầu kỳ (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_60),
                    b='{:,.0f}'.format(b01a_o),
                    d='{:,.0f}'.format(diff_l2),
                ))
        if amt_70 is not None and b01a_c is not None:
            diff_l1 = float_round(amt_70 - b01a_c, 2)
            if not float_is_zero(diff_l1, 2):
                danger = True
                warn_parts.append(_(
                    'LƯỚI L1: B03 mã 70 (%(a)s) lệch B01a 110 cuối kỳ (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_70),
                    b='{:,.0f}'.format(b01a_c),
                    d='{:,.0f}'.format(diff_l1),
                ))

        def _sum_codes(codes):
            total = 0.0
            for c in codes:
                v = by_code_amt.get(c)
                if v is None:
                    return None
                total = float_round(total + v, 2)
            return total

        sum_03_08 = _sum_codes(['03', '04', '05', '06', '07', '08'])
        sum_10_18 = _sum_codes([
            '10', '11', '12', '13', '14', '15', '16', '17', '18',
        ])
        sum_21_25 = _sum_codes(['21', '22', '23', '24', '25'])
        sum_31_35 = _sum_codes(['31', '32', '33', '34', '35'])
        amt_01 = by_code_amt.get('01')
        amt_02 = by_code_amt.get('02')
        amt_09 = by_code_amt.get('09')
        amt_20 = by_code_amt.get('20')
        amt_30 = by_code_amt.get('30')
        amt_40 = by_code_amt.get('40')
        amt_50 = by_code_amt.get('50')
        amt_61 = by_code_amt.get('61')
        amt_70 = by_code_amt.get('70')

        if amt_02 is not None and sum_03_08 is not None:
            grid_02 = float_round(amt_02 - sum_03_08, 2)
            if not float_is_zero(grid_02, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 02 (%(a)s) lệch Σ03…08 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_02),
                    b='{:,.0f}'.format(sum_03_08),
                    d='{:,.0f}'.format(grid_02),
                ))
        if amt_09 is not None and sum_10_18 is not None:
            grid_09 = float_round(amt_09 - sum_10_18, 2)
            if not float_is_zero(grid_09, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 09 (%(a)s) lệch Σ10…18 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_09),
                    b='{:,.0f}'.format(sum_10_18),
                    d='{:,.0f}'.format(grid_09),
                ))
        if (
            amt_01 is not None and sum_03_08 is not None
            and sum_10_18 is not None and amt_20 is not None
        ):
            expect_20 = float_round(amt_01 + sum_03_08 + sum_10_18, 2)
            grid_20 = float_round(amt_20 - expect_20, 2)
            if not float_is_zero(grid_20, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 20 (%(a)s) lệch 01+Σ03…08+Σ10…18 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_20),
                    b='{:,.0f}'.format(expect_20),
                    d='{:,.0f}'.format(grid_20),
                ))
        if amt_01 is not None and amt_02 is not None and amt_09 is not None and amt_20 is not None:
            expect_20b = float_round(amt_01 + amt_02 + amt_09, 2)
            grid_20b = float_round(amt_20 - expect_20b, 2)
            if not float_is_zero(grid_20b, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 20 (%(a)s) lệch 01+02+09 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_20),
                    b='{:,.0f}'.format(expect_20b),
                    d='{:,.0f}'.format(grid_20b),
                ))
        if amt_30 is not None and sum_21_25 is not None:
            grid_30 = float_round(amt_30 - sum_21_25, 2)
            if not float_is_zero(grid_30, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 30 (%(a)s) lệch Σ21…25 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_30),
                    b='{:,.0f}'.format(sum_21_25),
                    d='{:,.0f}'.format(grid_30),
                ))
        if amt_40 is not None and sum_31_35 is not None:
            grid_40 = float_round(amt_40 - sum_31_35, 2)
            if not float_is_zero(grid_40, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 40 (%(a)s) lệch Σ31…35 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_40),
                    b='{:,.0f}'.format(sum_31_35),
                    d='{:,.0f}'.format(grid_40),
                ))
        if (
            amt_50 is not None and amt_20 is not None
            and amt_30 is not None and amt_40 is not None
        ):
            expect_50 = float_round(amt_20 + amt_30 + amt_40, 2)
            grid_50 = float_round(amt_50 - expect_50, 2)
            if not float_is_zero(grid_50, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 50 (%(a)s) lệch 20+30+40 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_50),
                    b='{:,.0f}'.format(expect_50),
                    d='{:,.0f}'.format(grid_50),
                ))
        if (
            amt_70 is not None and amt_50 is not None
            and amt_60 is not None and amt_61 is not None
        ):
            expect_70 = float_round(amt_50 + amt_60 + amt_61, 2)
            grid_70 = float_round(amt_70 - expect_70, 2)
            if not float_is_zero(grid_70, 2):
                warn_parts.append(_(
                    'LƯỚI L3: mã 70 (%(a)s) lệch 50+60+61 (%(b)s) = %(d)s.',
                    a='{:,.0f}'.format(amt_70),
                    b='{:,.0f}'.format(expect_70),
                    d='{:,.0f}'.format(grid_70),
                ))

        diff_l4 = 0.0
        cash_ps_l4 = stage3_meta.get('cash_ps_l4')
        if cash_ps_l4 is not None and amt_50 is not None and amt_61 is not None:
            expect_l4 = float_round(amt_50 + amt_61, 2)
            diff_l4 = float_round(cash_ps_l4 - expect_l4, 2)
            if not float_is_zero(diff_l4, 2):
                danger = True
                warn_parts.append(_(
                    'LƯỚI L4: PS thuần quỹ 111/112 (%(cash)s) lệch mã 50+61 '
                    '(%(exp)s) = %(d)s — có thể còn luồng tiền chưa phân loại '
                    'hoặc lệch WC/điều chỉnh.',
                    cash='{:,.0f}'.format(cash_ps_l4),
                    exp='{:,.0f}'.format(expect_l4),
                    d='{:,.0f}'.format(diff_l4),
                ))

        warning = '\n'.join(warn_parts) if warn_parts else False
        warning_level = 'danger' if danger else ('warning' if warning else False)

        SnapLine = self.env['vas.report.snapshot.line']
        line_cmds = []
        for rl, period_amt in line_vals:
            line_cmds.append({
                'snapshot_id': self.id,
                'report_line_id': rl.id,
                'sequence': rl.sequence,
                'code': rl.code,
                'name': rl.name,
                'line_role': rl.line_role,
                'amount_opening': 0.0,
                'amount_closing': period_amt if period_amt is not None else 0.0,
                'is_na_opening': False,
                'is_na_closing': period_amt is None,
                'show_negative_paren': rl.show_negative_paren,
                'aggregate_by_partner': False,
            })
        if line_cmds:
            SnapLine.create(line_cmds)

        self.write({
            'warning_text': warning or False,
            'warning_level': warning_level or False,
            'check_b03_l1_diff': diff_l1,
            'check_b03_l2_diff': diff_l2,
            'check_b03_l4_diff': diff_l4,
            'meta_json': json.dumps({
                'total_na_children': total_na_map,
                'b01a_snapshot_id': b01a_snap.id,
                'b02_snapshot_id': b02_snap.id,
                'b02_50': by_code_amt.get('01'),
                'b01a_110_opening': b01a_o,
                'b01a_110_closing': b01a_c,
                'b03_stage2': stage2_meta,
                'b03_stage3': stage3_meta,
            }, ensure_ascii=False, default=str),
        })
        return True

    def _b03_move_kind_account_nets(
        self, company, account_id, date_from, date_to, hide_reversed, move_kinds,
    ):
        """SD đầu/cuối (net) của một TK chỉ từ bút toán ``move_kind`` cho trước.

        Đúng vài ``read_group`` cố định — không tăng theo số chỉ tiêu.
        """
        Line = self.env['vas.move.line']
        base = [
            ('company_id', '=', company.id),
            ('account_id', '=', account_id),
            ('move_id.move_kind', 'in', list(move_kinds)),
        ]
        if hide_reversed:
            base += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            base.append(('move_id.state', 'in', ('posted', 'reversed')))

        opening = 0.0
        for row in Line.read_group(
            base + [('date', '<', date_from)],
            ['debit:sum', 'credit:sum'],
            [],
            lazy=False,
        ):
            opening = float_round(
                opening + (row.get('debit') or 0.0) - (row.get('credit') or 0.0), 2,
            )
        ps_d = ps_c = 0.0
        for row in Line.read_group(
            base + [
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ],
            ['debit:sum', 'credit:sum'],
            [],
            lazy=False,
        ):
            ps_d = float_round(ps_d + (row.get('debit') or 0.0), 2)
            ps_c = float_round(ps_c + (row.get('credit') or 0.0), 2)
        closing = float_round(opening + ps_d - ps_c, 2)
        return opening, closing

    def _b03_compute_stage2(
        self, company, buckets, pairs, acc_by_code, ids_by_code, b02_by, warn_parts,
        report_lines=None, date_from=None, date_to=None, hide_reversed=True,
    ):
        """Tính mã 03–08, 10–14 (B03-2). Ghi cảnh báo vào warn_parts."""
        line_by_code = {rl.code: rl for rl in (report_lines or [])}

        def line_by_partner(code):
            rl = line_by_code.get(code)
            return bool(rl and rl.aggregate_by_partner)

        def codes_to_ids(code_list):
            ids = []
            for c in code_list:
                aid = ids_by_code.get(c)
                if aid:
                    ids.append(aid)
            return ids

        def debit_bal_delta(code_list, by_partner=False):
            """Δ SD Nợ = open_dr − close_dr (tăng SD Nợ → âm; giảm → dương).

            ``by_partner=True`` (chỉ công nợ): cộng riêng từng đối tác.
            ``False``: số dư thuần của tài khoản (PARTNER_ALL).
            """
            id_list = codes_to_ids(code_list)
            if not by_partner:
                total = 0.0
                for aid in id_list:
                    b = self._books_rollup_account(buckets, aid)
                    total = float_round(
                        total + (b['opening_debit'] - b['closing_debit']), 2,
                    )
                return total
            id_set = set(id_list)
            total = 0.0
            for (aid, _pid), b in buckets.items():
                if aid not in id_set:
                    continue
                o = b['opening']
                cl = b['closing']
                o_dr = o if o > 0 else 0.0
                c_dr = cl if cl > 0 else 0.0
                total = float_round(total + (o_dr - c_dr), 2)
            return total

        def credit_bal_delta(code_list, by_partner=False):
            """Δ SD Có = close_cr − open_cr (tăng SD Có → dương; giảm → âm).

            ``by_partner`` cùng quy ước với ``debit_bal_delta``.
            """
            id_list = codes_to_ids(code_list)
            if not by_partner:
                total = 0.0
                for aid in id_list:
                    b = self._books_rollup_account(buckets, aid)
                    total = float_round(
                        total + (b['closing_credit'] - b['opening_credit']), 2,
                    )
                return total
            id_set = set(id_list)
            total = 0.0
            for (aid, _pid), b in buckets.items():
                if aid not in id_set:
                    continue
                o = b['opening']
                cl = b['closing']
                o_cr = -o if o < 0 else 0.0
                c_cr = -cl if cl < 0 else 0.0
                total = float_round(total + (c_cr - o_cr), 2)
            return total

        def pair_amt(src_codes, src_side, opp_codes, opp_side):
            src_ids = codes_to_ids(src_codes)
            opp_ids = codes_to_ids(opp_codes)
            return self._books_counterpart_lookup(
                pairs, src_ids, src_side, opp_ids, opp_side,
            )

        # --- Mã 03 khấu hao ---
        dep_codes = ['2141', '2142', '2143', '2147']
        dep_gross = 0.0
        for code in dep_codes:
            acc = acc_by_code.get(code)
            if not acc:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            dep_gross = float_round(dep_gross + row['ps_credit'], 2)

        # Loại trừ KH vào XDCB dở dang (Có 214 ↔ Nợ 241*)
        dep_to_cip = pair_amt(dep_codes, 'credit', ['241', '2411', '2412', '2413'], 'debit')
        # Loại trừ hao mòn giảm quỹ KTPL / Quỹ PT KH&CN hình thành TSCĐ
        dep_vs_353 = pair_amt(dep_codes, 'credit', ['353', '3531', '3532', '3533', '3534'], 'debit')
        dep_vs_356 = pair_amt(
            dep_codes, 'credit', ['356', '3561', '3562'], 'debit',
        )
        # Chiều ngược (Nợ 214 giảm hao mòn) — không tự đoán; cảnh báo nếu có
        dep_reverse_353 = pair_amt(
            dep_codes, 'debit', ['353', '3531', '3532', '3533', '3534'], 'credit',
        )
        dep_reverse_356 = pair_amt(dep_codes, 'debit', ['356', '3561', '3562'], 'credit')

        exclude_mandatory = float_round(dep_to_cip + dep_vs_353 + dep_vs_356, 2)
        if float_is_zero(dep_to_cip, 2) and float_is_zero(dep_vs_353, 2) and float_is_zero(
            dep_vs_356, 2
        ):
            warn_parts.append(_(
                'Mã 03: chưa thấy cặp đối ứng KH (214*) ↔ XDCB (241*) / quỹ KTPL (353*) '
                '/ Quỹ PT KH&CN (356*). Câu bắt buộc loại trừ các khoản này vẫn áp dụng — '
                'nếu có phát sinh theo cách khác (không qua cặp đối ứng này) thì số mã 03 '
                'có thể chưa loại trừ đủ. Không đoán thêm.'
            ))
        if not float_is_zero(dep_reverse_353, 2) or not float_is_zero(dep_reverse_356, 2):
            warn_parts.append(_(
                'Mã 03: có phát sinh Nợ 214* đối ứng quỹ 353/356 (%(a)s / %(b)s) — '
                'chưa tự xếp vào loại trừ bắt buộc; cần rà tay.',
                a='{:,.0f}'.format(dep_reverse_353),
                b='{:,.0f}'.format(dep_reverse_356),
            ))

        dep_eligible = float_round(dep_gross - exclude_mandatory, 2)
        boc = bool(company.vas_boc_tach_khau_hao_htk)
        kh_htk = float_round(company.vas_khau_hao_trong_htk or 0.0, 2)
        if boc and float_is_zero(kh_htk, 2):
            warn_parts.append(_(
                'Cấu hình «Bóc tách được số khấu hao nằm trong hàng tồn kho» = Có nhưng '
                'chưa nhập số KH trong HTK cuối kỳ — không đoán. Mã 03/11 tạm tính như '
                'nhánh không bóc tách cho phần HTK (vẫn đã trừ loại trừ bắt buộc XDCB/quỹ).'
            ))
            boc_apply = False
            kh_htk_use = 0.0
        elif boc:
            boc_apply = True
            kh_htk_use = kh_htk
        else:
            boc_apply = False
            kh_htk_use = 0.0

        # Không bóc tách: 03 = toàn bộ KH hợp lệ (gồm phần trong HTK)
        # Có bóc tách + đã nhập: 03 = KH hợp lệ − KH trong HTK
        if boc_apply:
            amt_03 = float_round(dep_eligible - kh_htk_use, 2)
        else:
            amt_03 = dep_eligible

        # --- Mã 04 dự phòng ---
        prov_codes = [
            '2291', '2292', '2293', '2294',
            '352', '3521', '3522', '3524',
        ]
        # Không phải công nợ → số dư thuần (khai aggregate_by_partner=False)
        amt_04 = credit_bal_delta(prov_codes, by_partner=line_by_partner('04'))

        # --- Mã 05 CLTG đánh giá lại ---
        # Lãi (Có 413 ↔ Nợ 515) → trừ; lỗ (Nợ 413 ↔ Có 635) → cộng
        fx_gain = pair_amt(['413'], 'credit', ['515'], 'debit')
        fx_loss = pair_amt(['413'], 'debit', ['635'], 'credit')
        amt_05 = float_round(fx_loss - fx_gain, 2)
        # PS 413 còn lại không khớp cặp trên
        acc_413 = acc_by_code.get('413')
        if acc_413:
            row413 = self._books_rollup_account(buckets, acc_413.id)
            ps413 = float_round(row413['ps_debit'] + row413['ps_credit'], 2)
            matched = float_round(fx_gain + fx_loss, 2)
            if not float_is_zero(ps413 - matched, 2) and not float_is_zero(ps413, 2):
                warn_parts.append(_(
                    'Mã 05: PS TK 413 (%(ps)s) lệch phần khớp đối ứng 515/635 (%(m)s) — '
                    'phần còn lại chưa tách chi tiết ĐG lại; không đoán.',
                    ps='{:,.0f}'.format(ps413),
                    m='{:,.0f}'.format(matched),
                ))

        # --- Mã 06 lãi/lỗ HĐĐT (phần lấy được) ---
        # Lấy: thu nhập TC 515 (B02.21), TN khác 711 (B02.31), CP khác 811 (B02.32)
        # Net lãi đầu tư → trừ khỏi LNTT (số âm). Thiếu tách TL/NB → cảnh báo.
        def b02_close(code):
            row = b02_by.get(code)
            if not row or row.is_na_closing:
                return 0.0
            return float_round(row.amount_closing, 2)

        inv_21 = b02_close('21')  # dương = lãi
        inv_31 = b02_close('31')
        inv_32 = b02_close('32')  # B02 đã âm nếu lỗ
        # Net lãi = 21+31+32 (32 âm). Trừ khỏi LNTT → đảo dấu.
        amt_06 = float_round(-(inv_21 + inv_31 + inv_32), 2)
        ps_711_811 = 0.0
        for code in ('711', '811'):
            acc = acc_by_code.get(code)
            if not acc:
                continue
            row = self._books_rollup_account(buckets, acc.id)
            ps_711_811 = float_round(
                ps_711_811 + row['ps_debit'] + row['ps_credit'], 2,
            )
        if not float_is_zero(ps_711_811, 2):
            warn_parts.append(_(
                'Mã 06 chưa đầy đủ: có PS 711/811 (%(amt)s) nhưng thiếu chức năng '
                'thanh lý/nhượng bán tài sản (W8/C4) — đang lấy gộp theo B02 21/31/32, '
                'không tách đúng phần luồng đầu tư theo hướng dẫn. Mã 22 cùng lỗ. '
                'Không chặn lập báo cáo.',
                amt='{:,.0f}'.format(ps_711_811),
            ))
        else:
            warn_parts.append(_(
                'Mã 06: đang lấy phần có sẵn từ B02 mã 21/31/32 (515/711/811); '
                'chưa tách đủ mọi khoản HD đầu tư trên 632/635 theo hướng dẫn.'
            ))

        # --- Mã 07 chi phí lãi vay = B02.23 (cộng vào LNTT) ---
        amt_07 = b02_close('23')
        if b02_by.get('23') and b02_by['23'].is_na_closing:
            warn_parts.append(_(
                'Mã 07: bản B02 không có mã 23 hợp lệ — ghi 0, không đoán.'
            ))
            amt_07 = 0.0

        # --- Mã 08 chỉ TK 356 (Δ SD Có; không tách đối tác) ---
        amt_08 = credit_bal_delta(
            ['356', '3561', '3562'], by_partner=line_by_partner('08'),
        )

        # --- Mã 10 phải thu: Δ = open_dr − close_dr (tăng phải thu → âm) ---
        bp_10 = line_by_partner('10')
        recv_codes = [
            '131', '1361', '1368', '1381', '1386', '1388',
            '133', '1331', '1332', '141',
        ]
        # 331 chi tiết trả trước cho người bán = SD Nợ
        amt_10 = float_round(
            debit_bal_delta(recv_codes, by_partner=bp_10)
            + debit_bal_delta(['331'], by_partner=bp_10),
            2,
        )
        warn_parts.append(_(
            'Mã 10: chưa loại phải thu thuộc hoạt động đầu tư (thiếu nhãn trên chứng từ) — '
            'đang lấy toàn bộ phải thu SXKD theo danh mục TK; sẽ bổ sung ở chặng phân loại.'
        ))

        # --- Mã 11 hàng tồn kho: số dư thuần TK (không tách đối tác) ---
        inv_codes = ['151', '152', '153', '154', '155', '156', '157']
        amt_11 = debit_bal_delta(inv_codes, by_partner=line_by_partner('11'))
        # Không gồm 2294 (đã ở mã 04). Loại trừ HTK dùng XDCB — chưa tách → cảnh báo
        warn_parts.append(_(
            'Mã 11: chưa loại giá trị HTK dùng cho XDCB / đổi TSCĐ (thiếu phân loại mục đích) — '
            'đang lấy toàn bộ SD tồn kho; không âm thầm bỏ qua câu loại trừ.'
        ))
        if boc_apply:
            # Bóc tách: mã 11 không gồm KH trong HTK cuối → cộng thêm số KH đã loại khỏi 03
            amt_11 = float_round(amt_11 + kh_htk_use, 2)

        # --- Mã 12 phải trả: Δ = close_cr − open_cr (tăng phải trả → dương) ---
        # HD 15581 tr.48: gồm TK 331,333,334,335,336,338,131 (người mua trả trước);
        # loại thuế TNDN (3334) và lãi vay phải trả (chi tiết lãi trên 335).
        bp_12 = line_by_partner('12')
        pay_codes = [
            '331',  # credit side via credit_bal_delta
            '333', '3331', '3332', '3333', '3335', '3336', '3337', '3338', '3339',
            '33311', '33312', '33381', '33382',
            # 3334 excluded (TNDN)
            '334',
            '335',
            '336', '3361', '3368',
            '338', '3381', '3382', '3383', '3384', '3385', '3386', '3387', '3388',
            '131',  # người mua trả trước = SD Có
        ]
        amt_12 = credit_bal_delta(pay_codes, by_partner=bp_12)

        # Loại phần lãi vay phải trả trên 335 (bút toán vas.loan → move_kind=loan_interest)
        acc_335 = acc_by_code.get('335')
        interest_335_delta = 0.0
        other_335_delta = 0.0
        if acc_335 and date_from and date_to:
            full_335 = credit_bal_delta(['335'], by_partner=bp_12)
            o_int, c_int = self._b03_move_kind_account_nets(
                company, acc_335.id, date_from, date_to, hide_reversed,
                ('loan_interest',),
            )
            o_cr = -o_int if o_int < 0 else 0.0
            c_cr = -c_int if c_int < 0 else 0.0
            interest_335_delta = float_round(c_cr - o_cr, 2)
            other_335_delta = float_round(full_335 - interest_335_delta, 2)
            if not float_is_zero(interest_335_delta, 2):
                amt_12 = float_round(amt_12 - interest_335_delta, 2)
            if not float_is_zero(other_335_delta, 2):
                warn_parts.append(_(
                    'Mã 12: TK 335 còn Δ SD Có %(amt)s không gắn bút toán vas.loan '
                    '(move_kind=loan_interest) — đang đưa vào mã 12; nếu là lãi vay '
                    'phải trả thì cần ghi nhận qua vas.loan.',
                    amt='{:,.0f}'.format(other_335_delta),
                ))
        warn_parts.append(_(
            'Mã 12: chưa loại phải trả thuộc hoạt động đầu tư/tài chính (thiếu nhãn) — '
            'đang lấy theo danh mục TK đã loại 3334 và 341*; lãi vay 335 (vas.loan) đã trừ.'
        ))

        # --- Mã 13 chi phí trả trước 242: số dư thuần ---
        amt_13 = debit_bal_delta(['242'], by_partner=line_by_partner('13'))
        warn_parts.append(_(
            'Mã 13: chưa loại chi phí trả trước thuộc luồng đầu tư (thuê đất / lãi vay '
            'vốn hóa) — đang lấy toàn bộ TK 242; không đoán phần loại trừ.'
        ))

        # --- Mã 14 chứng khoán KD 121: số dư thuần ---
        amt_14 = debit_bal_delta(['121'], by_partner=line_by_partner('14'))

        out = {
            '03': amt_03,
            '04': amt_04,
            '05': amt_05,
            '06': amt_06,
            '07': amt_07,
            '08': amt_08,
            '10': amt_10,
            '11': amt_11,
            '12': amt_12,
            '13': amt_13,
            '14': amt_14,
        }
        meta = {
            'dep_gross': dep_gross,
            'dep_exclude_mandatory': exclude_mandatory,
            'dep_to_cip': dep_to_cip,
            'boc_tach': boc,
            'boc_apply': boc_apply,
            'kh_htk': kh_htk_use,
            'amt_03': amt_03,
            'amt_07': amt_07,
        }
        return out, meta

    B03_STAGE3_CODES = (
        '15', '16', '17', '18',
        '21', '22', '23', '24', '25',
        '31', '32', '33', '34', '35',
        '61',
    )
    B03_STAGE3_OUTFLOW = frozenset({
        '15', '16', '18', '21', '23', '32', '34', '35',
    })
    # Không gồm account.move: VAS không đọc bút toán tổng hợp Odoo cho LCTT;
    # misc V02/V06 (entry) cũng không sinh PS 111/112.
    B03_CF_SOURCE_MODELS = frozenset({
        'account.payment', 'vas.debt.offset',
    })

    @api.model
    def _b03_cash_account_ids(self, acc_by_code):
        """TK tiền 111* / 112* theo danh mục chế độ."""
        ids = []
        for code, acc in acc_by_code.items():
            if code.startswith('111') or code.startswith('112'):
                ids.append(acc.id)
        return ids

    @staticmethod
    def _b03_code_matches_prefixes(code, prefixes):
        for pfx in prefixes:
            if pfx.endswith('*'):
                if code.startswith(pfx[:-1]):
                    return True
            elif code == pfx or code.startswith(pfx):
                return True
        return False

    @classmethod
    def _b03_any_code_matches(cls, codes, prefixes):
        for code in codes:
            if cls._b03_code_matches_prefixes(code, prefixes):
                return True
        return False

    @api.model
    def _b03_map_cash_flow_indicator(
        self, activity, op_type, net_cash, cp_codes, warn_parts, move_label,
    ):
        """Map một PS quỹ đã có activity → mã 15–18 / 21–25 / 31–35 hoặc None."""
        if not activity:
            return None, 'unclassified'
        if activity == 'none':
            return None, 'exclude'

        if op_type in ('loan_interest_pay', 'loan_interest_pay_direct'):
            return '15', 'mapped'
        if net_cash < 0 and self._b03_any_code_matches(cp_codes, ['3334']):
            return '16', 'mapped'
        if op_type == 'loan_receipt':
            return '33', 'mapped'
        if op_type == 'loan_repay':
            return '34', 'mapped'
        if op_type == 'capital_receipt':
            return '31', 'mapped'
        if op_type in ('dividend_pay', 'dividend_tax_pay'):
            return '35', 'mapped'

        if activity == 'investing':
            if net_cash < 0 and self._b03_any_code_matches(
                cp_codes, ['21', '24', '241'],
            ):
                return '21', 'mapped'
            # 711/811: phần lấy được cho mã 22 (TL/NB chưa đủ — cảnh báo ở stage2)
            if self._b03_any_code_matches(cp_codes, ['711', '811']):
                return '22', 'mapped'
            if net_cash < 0 and self._b03_any_code_matches(
                cp_codes, ['128', '221', '222'],
            ):
                return '23', 'mapped'
            if net_cash > 0 and self._b03_any_code_matches(cp_codes, ['515']):
                return '25', 'mapped'
            if net_cash > 0:
                return '24', 'mapped'
            warn_parts.append(_(
                'B03 chi tiền đầu tư chưa xếp mã 21–25: %(mv)s, '
                'số %(amt)s — cần rà nhãn/đối ứng.',
                mv=move_label,
                amt='{:,.0f}'.format(net_cash),
            ))
            return None, 'warn'

        if activity == 'financing':
            if net_cash > 0 and self._b03_any_code_matches(cp_codes, ['411']):
                return '31', 'mapped'
            if net_cash < 0 and self._b03_any_code_matches(cp_codes, ['411', '419']):
                return '32', 'mapped'
            warn_parts.append(_(
                'B03 chi tiền tài chính chưa xếp mã 31–35: %(mv)s, '
                'số %(amt)s — cần rà nhãn/đối ứng.',
                mv=move_label,
                amt='{:,.0f}'.format(net_cash),
            ))
            return None, 'warn'

        # operating: 15/16 đã xử lý; còn lại nằm trong WC 10–14 — không 17/18
        return None, 'operating_wc'

    @api.model
    def _b03_signed_stage3_amount(self, indicator, net_cash):
        if float_is_zero(net_cash, 2):
            return 0.0
        # Mã 22: thuần thu−chi TL/NB (có thể âm khi mới lấy được phần 811)
        if indicator == '22':
            return float_round(net_cash, 2)
        if indicator in self.B03_STAGE3_OUTFLOW:
            return float_round(-abs(net_cash), 2)
        return float_round(abs(net_cash), 2)

    def _b03_collect_classified_cash(
        self, company, acc_by_code, warn_parts,
        date_from=None, date_to=None, hide_reversed=True,
    ):
        """Một pass: PS quỹ theo vas.move + activity trên chứng từ nguồn."""
        cash_ids = self._b03_cash_account_ids(acc_by_code)
        if not cash_ids or not date_from or not date_to:
            return {}, 0.0, {
                'moves': 0, 'unclassified': 0, 'excluded_none': 0,
            }

        Line = self.env['vas.move.line']
        Move = self.env['vas.move']
        cash_id_set = set(cash_ids)
        base = [
            ('company_id', '=', company.id),
            ('account_id', 'in', cash_ids),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.move_kind', '!=', 'opening'),
        ]
        if hide_reversed:
            base += Move.domain_for_amounts(prefix='move_id')
        else:
            base.append(('move_id.state', 'in', ('posted', 'reversed')))

        cash_by_move = {}
        for row in Line.read_group(
            base, ['debit:sum', 'credit:sum'], ['move_id'], lazy=False,
        ):
            mid = row['move_id'][0]
            deb = row.get('debit') or 0.0
            cred = row.get('credit') or 0.0
            cash_by_move[mid] = float_round(deb - cred, 2)

        if not cash_by_move:
            return {}, 0.0, {
                'moves': 0, 'unclassified': 0, 'excluded_none': 0,
            }

        move_ids = list(cash_by_move.keys())
        moves = Move.browse(move_ids)
        move_info = {
            m.id: {
                'name': m.display_name,
                'ref': m.ref or '',
                'source_model': m.source_model,
                'source_res_id': m.source_res_id,
            } for m in moves
        }

        cp_codes_by_move = {mid: set() for mid in move_ids}
        for line in Line.search([
            ('move_id', 'in', move_ids),
            ('account_id', 'not in', cash_ids),
        ]):
            cp_codes_by_move[line.move_id.id].add(line.account_id.code)

        # Batch load activity từ nguồn (không account.move — xem B03_CF_SOURCE_MODELS)
        src_ids = {'account.payment': [], 'vas.debt.offset': []}
        for info in move_info.values():
            sm = info['source_model']
            sr = info['source_res_id']
            if sm in src_ids and sr:
                src_ids[sm].append(sr)

        activity_by_src = {}
        op_by_src = {}
        for model, ids in src_ids.items():
            if not ids or model not in self.env:
                continue
            for rec in self.env[model].browse(list(set(ids))).exists():
                activity_by_src[(model, rec.id)] = rec.vas_cash_flow_activity
                op_by_src[(model, rec.id)] = getattr(
                    rec, 'vas_operation_type', False,
                )

        totals = {c: 0.0 for c in self.B03_STAGE3_CODES}
        cash_ps_l4 = 0.0
        meta = {
            'moves': len(move_ids),
            'unclassified': 0,
            'excluded_none': 0,
            'operating_wc': 0,
            'mapped': 0,
        }

        for mid, net_cash in cash_by_move.items():
            if float_is_zero(net_cash, 2):
                continue
            info = move_info[mid]
            sm = info['source_model']
            sr = info['source_res_id']
            activity = op = False
            if sm in self.B03_CF_SOURCE_MODELS and sr:
                activity = activity_by_src.get((sm, sr))
                op = op_by_src.get((sm, sr))

            label = info['name']
            if info['ref']:
                label = '%s / %s' % (label, info['ref'])

            indicator, status = self._b03_map_cash_flow_indicator(
                activity, op, net_cash,
                cp_codes_by_move.get(mid, set()),
                warn_parts, label,
            )

            if status == 'exclude':
                meta['excluded_none'] += 1
                continue

            if status == 'unclassified':
                meta['unclassified'] += 1
                warn_parts.append(_(
                    'Luồng tiền chưa phân loại: %(mv)s, số %(amt)s — '
                    'gắn hoạt động LCTT trên chứng từ nguồn.',
                    mv=label,
                    amt='{:,.0f}'.format(net_cash),
                ))
                cash_ps_l4 = float_round(cash_ps_l4 + net_cash, 2)
                continue

            cash_ps_l4 = float_round(cash_ps_l4 + net_cash, 2)

            if status == 'operating_wc':
                meta['operating_wc'] += 1
                continue

            if indicator:
                signed = self._b03_signed_stage3_amount(indicator, net_cash)
                totals[indicator] = float_round(
                    totals[indicator] + signed, 2,
                )
                meta['mapped'] += 1

        return totals, cash_ps_l4, meta

    def _b03_compute_stage3(
        self, company, acc_by_code, warn_parts,
        date_from=None, date_to=None, hide_reversed=True,
    ):
        """Tính mã 15–18, 21–25, 31–35, 61 (B03-3)."""
        totals, cash_ps_l4, collect_meta = self._b03_collect_classified_cash(
            company, acc_by_code, warn_parts,
            date_from=date_from, date_to=date_to, hide_reversed=hide_reversed,
        )
        out = {code: totals.get(code, 0.0) for code in self.B03_STAGE3_CODES}
        # 61 = 0 tạm thời (FX chưa tách)
        out['61'] = 0.0
        if not float_is_zero(out.get('61', 0.0), 2):
            warn_parts.append(_(
                'Mã 61: chưa tách ảnh hưởng CLTG quy đổi — đang ghi 0.'
            ))
        meta = dict(collect_meta)
        meta['cash_ps_l4'] = cash_ps_l4
        meta['totals'] = dict(out)
        return out, meta

    # -------------------------------------------------------------------------
    # Generate B09 — khung + số lấy từ bản B01a/B02 đã lập (không quét sổ)
    # -------------------------------------------------------------------------

    @api.model
    def _find_period_snapshot(self, form_code, company, period_from, period_to):
        """Bản đã lập mới nhất cùng công ty + từ kỳ + đến kỳ. Không tự lập."""
        return self.search([
            ('form_code', '=', form_code),
            ('company_id', '=', company.id),
            ('period_from_id', '=', period_from.id),
            ('period_to_id', '=', period_to.id),
        ], order='date_computed desc, id desc', limit=1)

    @api.model
    def generate_b09(
        self, company, period_from, period_to, hide_reversed=True,
        copy_prior_year=True,
    ):
        """Lập B09 từ bản B01a+B02 đã lưu; chi tiết machine_now lấy thêm từ sổ/text."""
        if not company.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if period_from.date_start > period_to.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (period_from, period_to):
            if p.fiscalyear_id.company_id != company:
                raise UserError(_(
                    'Kỳ %(p)s không thuộc công ty đang chọn.',
                    p=p.display_name,
                ))

        b01a = self._find_period_snapshot(
            'B01a-DNN', company, period_from, period_to,
        )
        b02 = self._find_period_snapshot(
            'B02-DNN', company, period_from, period_to,
        )
        missing = []
        if not b01a:
            missing.append(_('B01a-DNN'))
        if not b02:
            missing.append(_('B02-DNN'))
        if missing:
            raise UserError(_(
                'Chưa lập %(forms)s cho công ty «%(co)s» kỳ %(a)s → %(b)s. '
                'Phải lập hai báo cáo đó trước — B09 không tự lập ngầm và '
                'không điền 0 thay thế.',
                forms=', '.join(missing),
                co=company.display_name,
                a=period_from.name,
                b=period_to.name,
            ))

        Entry = self.env['vas.b09.entry']
        # Kỳ mới trống → chép nền năm trước (đánh dấu); rồi gợi ý máy cho chỗ trống
        if copy_prior_year:
            Entry.copy_from_prior_year(
                company, period_from, period_to, only_if_empty=True,
            )
        Entry.ensure_suggestions(company, period_from, period_to)

        now = fields.Datetime.now()
        snap = self.create({
            'name': _('B09 %(a)s → %(b)s') % {
                'a': period_from.name, 'b': period_to.name,
            },
            'form_code': 'B09-DNN',
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'date_computed': now,
            'user_id': self.env.user.id,
            'hide_reversed': hide_reversed,
            'currency_id': company.currency_id.id or self.env.ref('base.VND').id,
        })
        snap._store_b09_from_snapshots(b01a, b02)
        return snap

    def _b09_accounts_tree(self, codes, acc_by_code, children_by_parent):
        """TK theo mã + mọi tài khoản con (cây)."""
        Account = self.env['vas.account']
        found = Account.browse()
        missing = []
        for code in codes:
            root = acc_by_code.get(code)
            if not root:
                missing.append(code)
                continue
            stack = [root]
            while stack:
                cur = stack.pop()
                found |= cur
                stack.extend(list(children_by_parent.get(cur.id, Account.browse())))
        return found, missing

    def _store_b09_from_snapshots(self, b01a_snap, b02_snap):
        """B01a/B02 đã lập + sổ (một lần) + text FY/currency → ghi B09."""
        self.ensure_one()
        if self.is_submitted:
            raise UserError(_('Bản đã nộp — không tính lại vào bản này.'))

        entry_by_code = self.env['vas.b09.entry'].map_for_period(
            self.company_id, self.period_from_id, self.period_to_id,
        )

        ReportLine = self.env['vas.report.line']
        lines_def = ReportLine.search([
            ('form_code', '=', 'B09-DNN'),
            ('regime_id', '=', self.regime_id.id),
            ('active', '=', True),
        ])

        b01a_by = {l.code: l for l in b01a_snap.line_ids}
        b02_by = {l.code: l for l in b02_snap.line_ids}

        b01a_snap._compute_ledger_changed()
        b02_snap._compute_ledger_changed()

        def _b09_key(rl):
            return (rl.code_custom_key or '').strip()

        need_ledger = any(
            _b09_key(rl) == 'b09_from_ledger'
            or _b09_key(rl).startswith('b09_from_movement:')
            for rl in lines_def
        )
        need_cp = any(
            _b09_key(rl) == 'b09_from_ledger'
            and rl.turnover_mode == 'counterpart'
            for rl in lines_def
        )
        buckets = {}
        pairs = {}
        acc_by_code = {}
        children_by_parent = {}
        if need_ledger:
            date_from = self.period_from_id.date_start
            date_to = self.period_to_id.date_end
            buckets = self._books_aggregate_buckets(
                self.company_id, date_from, date_to, self.hide_reversed,
            )
            if need_cp:
                pairs = self._books_counterpart_pairs(
                    self.company_id, date_from, date_to, self.hide_reversed,
                )['pairs']
            Account = self.env['vas.account']
            all_acc = Account.search([('regime_id', '=', self.regime_id.id)])
            acc_by_code = {a.code: a for a in all_acc}
            for a in all_acc:
                if a.parent_id:
                    children_by_parent.setdefault(
                        a.parent_id.id, Account.browse(),
                    )
                    children_by_parent[a.parent_id.id] |= a

        table_warns = []
        seen_warn = set()
        grid_rows = []
        danger = False
        line_cmds = []
        computed = {}  # code -> {o,i,d,c, na_*}
        decrease_codes = []

        def side_amt(bucket, side, which):
            if side == 'debit':
                return bucket[
                    'opening_debit' if which == 'opening' else 'closing_debit'
                ]
            if side == 'credit':
                return bucket[
                    'opening_credit' if which == 'opening' else 'closing_credit'
                ]
            if side == 'signed_credit':
                return -bucket['opening' if which == 'opening' else 'closing']
            if side == 'signed_debit':
                return bucket['opening' if which == 'opening' else 'closing']
            return 0.0

        def rollup_codes(codes):
            accs, missing_acc = self._b09_accounts_tree(
                codes, acc_by_code, children_by_parent,
            )
            return accs, missing_acc

        for rl in lines_def.sorted(lambda r: (r.sequence, r.code)):
            key = (rl.code_custom_key or '').strip()
            opening = 0.0
            increase = 0.0
            decrease = 0.0
            closing = 0.0
            na_o = True
            na_i = True
            na_d = True
            na_c = True
            text_val = False
            table_json = False
            value_source = 'empty'
            from_prior = False
            confirmed = True

            if rl.warn_message and rl.warn_message not in seen_warn:
                seen_warn.add(rl.warn_message)

            if key == 'b09_section':
                value_source = 'section'
            elif key == 'b09_unavailable':
                pass
            elif key.startswith('b09_from_text:'):
                kind = key.split(':', 1)[1].strip()
                if kind == 'fiscalyear':
                    fy = self.period_to_id.fiscalyear_id
                    if fy and fy.date_from and fy.date_to:
                        text_val = _('%(a)s – %(b)s') % {
                            'a': fy.date_from.strftime('%d/%m/%Y'),
                            'b': fy.date_to.strftime('%d/%m/%Y'),
                        }
                elif kind == 'currency':
                    cur = self.company_id.currency_id
                    if cur:
                        text_val = cur.name or cur.display_name
                if text_val:
                    value_source = 'machine_text'
                    na_c = False
                else:
                    table_warns.append(_(
                        'B09 %(code)s: không lấy được text nguồn (%(k)s).',
                        code=rl.code, k=kind,
                    ))
            elif key.startswith('b09_from_b01a:'):
                src_code = key.split(':', 1)[1].strip()
                src = b01a_by.get(src_code)
                if not src:
                    msg = _(
                        'LƯỚI B09: %(b09)s cần B01a mã %(src)s nhưng bản B01a '
                        'đã lập không có chỉ tiêu đó.',
                        b09=rl.code, src=src_code,
                    )
                    table_warns.append(msg)
                    danger = True
                    grid_rows.append({
                        'b09_code': rl.code,
                        'source_form': 'B01a-DNN',
                        'source_code': src_code,
                        'diff_opening': None,
                        'diff_closing': None,
                        'missing_source': True,
                    })
                else:
                    opening = src.amount_opening
                    closing = src.amount_closing
                    na_o = bool(src.is_na_opening)
                    na_c = bool(src.is_na_closing)
                    value_source = 'machine_report'
                    diff_o = 0.0
                    diff_c = 0.0
                    if not na_o and not float_is_zero(
                        opening - src.amount_opening, 2,
                    ):
                        diff_o = float_round(opening - src.amount_opening, 2)
                    if not na_c and not float_is_zero(
                        closing - src.amount_closing, 2,
                    ):
                        diff_c = float_round(closing - src.amount_closing, 2)
                    grid_rows.append({
                        'b09_code': rl.code,
                        'source_form': 'B01a-DNN',
                        'source_code': src_code,
                        'source_opening': None if na_o else src.amount_opening,
                        'source_closing': None if na_c else src.amount_closing,
                        'diff_opening': diff_o,
                        'diff_closing': diff_c,
                        'missing_source': False,
                    })
                    if not float_is_zero(diff_o, 2) or not float_is_zero(diff_c, 2):
                        danger = True
                        table_warns.append(_(
                            'LƯỚI B09 ĐẬM: %(b09)s lệch chỉ tiêu nguồn B01a %(src)s '
                            '(đầu %(do)s / cuối %(dc)s). Vẫn in số đã lưu trên B09.',
                            b09=rl.code, src=src_code,
                            do='{:,.0f}'.format(diff_o),
                            dc='{:,.0f}'.format(diff_c),
                        ))
            elif key.startswith('b09_from_b02:'):
                src_code = key.split(':', 1)[1].strip()
                src = b02_by.get(src_code)
                if not src:
                    msg = _(
                        'LƯỚI B09: %(b09)s cần B02 mã %(src)s nhưng bản B02 '
                        'đã lập không có chỉ tiêu đó.',
                        b09=rl.code, src=src_code,
                    )
                    table_warns.append(msg)
                    danger = True
                    grid_rows.append({
                        'b09_code': rl.code,
                        'source_form': 'B02-DNN',
                        'source_code': src_code,
                        'diff_opening': None,
                        'diff_closing': None,
                        'missing_source': True,
                    })
                else:
                    opening = 0.0
                    na_o = True
                    closing = src.amount_closing
                    na_c = bool(src.is_na_closing)
                    value_source = 'machine_report'
                    diff_c = 0.0
                    if not na_c and not float_is_zero(
                        closing - src.amount_closing, 2,
                    ):
                        diff_c = float_round(closing - src.amount_closing, 2)
                    grid_rows.append({
                        'b09_code': rl.code,
                        'source_form': 'B02-DNN',
                        'source_code': src_code,
                        'source_opening': None,
                        'source_closing': None if na_c else src.amount_closing,
                        'diff_opening': None,
                        'diff_closing': diff_c,
                        'missing_source': False,
                    })
                    if not float_is_zero(diff_c, 2):
                        danger = True
                        table_warns.append(_(
                            'LƯỚI B09 ĐẬM: %(b09)s lệch chỉ tiêu nguồn B02 %(src)s '
                            '(năm nay %(dc)s). Vẫn in số đã lưu trên B09.',
                            b09=rl.code, src=src_code,
                            dc='{:,.0f}'.format(diff_c),
                        ))
            elif key.startswith('b09_from_movement:'):
                kind = key.split(':', 1)[1].strip()
                codes = ReportLine._parse_codes(rl.account_codes)
                accs, missing_acc = rollup_codes(codes)
                if missing_acc:
                    table_warns.append(_(
                        'B09 %(code)s thiếu TK trên chart: %(acc)s — không điền 0.',
                        code=rl.code, acc=', '.join(missing_acc),
                    ))
                    danger = True
                else:
                    o_sum = i_sum = d_sum = c_sum = 0.0
                    for acc in accs:
                        b = self._books_rollup_account(buckets, acc.id)
                        if kind == 'accum':
                            o_sum = float_round(
                                o_sum + side_amt(b, 'credit', 'opening'), 2,
                            )
                            c_sum = float_round(
                                c_sum + side_amt(b, 'credit', 'closing'), 2,
                            )
                            i_sum = float_round(i_sum + b['ps_credit'], 2)
                            d_sum = float_round(d_sum + b['ps_debit'], 2)
                        else:
                            o_sum = float_round(
                                o_sum + side_amt(b, 'debit', 'opening'), 2,
                            )
                            c_sum = float_round(
                                c_sum + side_amt(b, 'debit', 'closing'), 2,
                            )
                            i_sum = float_round(i_sum + b['ps_debit'], 2)
                            d_sum = float_round(d_sum + b['ps_credit'], 2)
                    opening, increase, decrease, closing = (
                        o_sum, i_sum, d_sum, c_sum,
                    )
                    na_o = na_i = na_d = na_c = False
                    value_source = 'machine_ledger'
                    if not float_is_zero(decrease, 2):
                        decrease_codes.append(rl.code)
            elif key.startswith('b09_from_net:'):
                parts = key.split(':', 1)[1].strip().split(',')
                if len(parts) != 2:
                    raise UserError(_(
                        'Chỉ tiêu B09 %(code)s: b09_from_net cần đúng 2 mã '
                        '(nguyên giá, hao mòn).',
                        code=rl.code,
                    ))
                cost = computed.get(parts[0].strip())
                accum = computed.get(parts[1].strip())
                if not cost or not accum:
                    table_warns.append(_(
                        'B09 %(code)s: chưa có số nguyên giá/hao mòn nguồn '
                        '(%(a)s / %(b)s).',
                        code=rl.code, a=parts[0], b=parts[1],
                    ))
                    danger = True
                else:
                    opening = float_round(cost['o'] - accum['o'], 2)
                    increase = float_round(cost['i'] - accum['i'], 2)
                    decrease = float_round(cost['d'] - accum['d'], 2)
                    closing = float_round(cost['c'] - accum['c'], 2)
                    na_o = na_i = na_d = na_c = False
                    value_source = 'machine_ledger'
            elif key == 'b09_from_ledger':
                codes = ReportLine._parse_codes(rl.account_codes)
                accs, missing_acc = rollup_codes(codes)
                if missing_acc:
                    table_warns.append(_(
                        'B09 %(code)s thiếu TK trên chart: %(acc)s — không điền 0.',
                        code=rl.code, acc=', '.join(missing_acc),
                    ))
                    danger = True
                elif rl.turnover_mode == 'counterpart':
                    opp_codes = ReportLine._parse_codes(
                        rl.counterpart_account_codes,
                    )
                    opp_accs, miss_opp = rollup_codes(opp_codes)
                    if miss_opp:
                        table_warns.append(_(
                            'B09 %(code)s thiếu TK đối ứng: %(acc)s.',
                            code=rl.code, acc=', '.join(miss_opp),
                        ))
                        danger = True
                    else:
                        amt = self._books_counterpart_lookup(
                            pairs,
                            accs.ids,
                            rl.source_side or 'credit',
                            opp_accs.ids,
                            rl.counterpart_side or 'debit',
                        )
                        if rl.sign_negative:
                            amt = float_round(-amt, 2)
                        opening = 0.0
                        na_o = True
                        closing = amt
                        na_c = False
                        value_source = 'machine_ledger'
                elif rl.turnover_mode == 'gross':
                    side = rl.source_side or 'credit'
                    amt = 0.0
                    for acc in accs:
                        b = self._books_rollup_account(buckets, acc.id)
                        amt = float_round(
                            amt + (
                                b['ps_credit'] if side == 'credit'
                                else b['ps_debit']
                            ),
                            2,
                        )
                    if rl.sign_negative:
                        amt = float_round(-amt, 2)
                    opening = 0.0
                    na_o = True
                    closing = amt
                    na_c = False
                    value_source = 'machine_ledger'
                else:
                    side = rl.balance_side or 'debit'
                    o_sum = c_sum = 0.0
                    for acc in accs:
                        b = self._books_rollup_account(buckets, acc.id)
                        o_sum = float_round(
                            o_sum + side_amt(b, side, 'opening'), 2,
                        )
                        c_sum = float_round(
                            c_sum + side_amt(b, side, 'closing'), 2,
                        )
                    opening = o_sum
                    closing = c_sum
                    na_o = False
                    na_c = False
                    value_source = 'machine_ledger'
            elif rl.amount_source == 'code_custom':
                raise UserError(_(
                    'Chỉ tiêu B09 %(code)s có code_custom_key không hỗ trợ: %(key)s. '
                    'Được phép: b09_section, b09_unavailable, b09_from_b01a:*, '
                    'b09_from_b02:*, b09_from_ledger, b09_from_movement:*, '
                    'b09_from_net:*, b09_from_text:*.',
                    code=rl.code, key=key or '(trống)',
                ))
            else:
                raise UserError(_(
                    'Chỉ tiêu B09 %(code)s phải dùng amount_source=code_custom '
                    '(hiện: %(src)s).',
                    code=rl.code, src=rl.amount_source,
                ))

            # Overlay nội dung người điền / gợi ý (kho tách — không mất khi lập lại)
            if rl.code in B09_ENTRY_CODES:
                ent = entry_by_code.get(rl.code)
                if ent and ent.is_filled():
                    payload = ent.to_snapshot_payload()
                    if ent.content_kind == 'text':
                        text_val = payload['text']
                        na_c = False
                    elif ent.content_kind == 'amount':
                        opening = payload['o']
                        closing = payload['c']
                        na_o = payload['na_o']
                        na_c = payload['na_c']
                    else:
                        table_json = payload['table_json']
                        na_c = False
                    value_source = ent.snapshot_value_source()
                    from_prior = bool(ent.is_from_prior_year)
                    confirmed = bool(ent.is_confirmed)
                elif value_source in ('empty', 'section'):
                    value_source = 'empty'

            computed[rl.code] = {
                'o': opening if not na_o else 0.0,
                'i': increase if not na_i else 0.0,
                'd': decrease if not na_d else 0.0,
                'c': closing if not na_c else 0.0,
                'na_o': na_o,
                'na_c': na_c,
            }
            line_cmds.append({
                'snapshot_id': self.id,
                'report_line_id': rl.id,
                'sequence': rl.sequence,
                'code': rl.code,
                'name': rl.name,
                'line_role': rl.line_role,
                'amount_opening': opening if not na_o else 0.0,
                'amount_increase': increase if not na_i else 0.0,
                'amount_decrease': decrease if not na_d else 0.0,
                'amount_closing': closing if not na_c else 0.0,
                'is_na_opening': na_o,
                'is_na_increase': na_i,
                'is_na_decrease': na_d,
                'is_na_closing': na_c,
                'show_negative_paren': rl.show_negative_paren,
                'aggregate_by_partner': False,
                'b09_fill_kind': rl.b09_fill_kind or False,
                'b09_gap_reason': rl.b09_gap_reason or False,
                'b09_table_status': rl.b09_table_status or False,
                'b09_table_status_note': rl.b09_table_status_note or False,
                'b09_text_value': text_val or False,
                'b09_table_json': table_json or False,
                'b09_value_source': value_source,
                'b09_is_from_prior': from_prior,
                'b09_is_confirmed': confirmed,
            })

        if decrease_codes:
            table_warns.append(_(
                'B09 bảng tăng/giảm TSCĐ/BĐSĐT: cột giảm có số trên %(codes)s '
                'nhưng chưa có chức năng thanh lý/nhượng bán — số giảm chưa được '
                'phân tích theo nguyên nhân.',
                codes=', '.join(decrease_codes),
            ))
        if any(
            (rl.code_custom_key or '').strip() == 'b09_unavailable'
            and rl.code in ('V.6.rent', 'V.6.hold')
            for rl in lines_def
        ):
            # Cảnh báo tách loại khi đã có bảng 217/2147
            cost_c = computed.get('V.6.cost', {}).get('c') or 0.0
            accum_c = computed.get('V.6.accum', {}).get('c') or 0.0
            if not float_is_zero(cost_c, 2) or not float_is_zero(accum_c, 2):
                table_warns.append(_(
                    'B09 V.6: đã lấy số bảng tăng/giảm từ TK 217/2147; phần tách '
                    '«cho thuê» / «chờ tăng giá» vẫn trống — thiếu phân loại trên '
                    'thẻ/tiểu khoản.',
                ))

        # Lưới tự kiểm: ∑ chi tiết ≠ dòng tổng (từ B01a/B02) → cảnh báo, không chặn
        detail_sum_rows = []
        for total_code, spec in B09_DETAIL_SUM_CHECKS.items():
            tot = computed.get(total_code)
            if not tot:
                continue
            detail_codes = spec['details']
            source_label = spec['source_label']
            check_opening = spec.get('check_opening', False)
            for which, na_key, amt_key, col_lbl in (
                ('closing', 'na_c', 'c', _('cuối kỳ')),
                ('opening', 'na_o', 'o', _('đầu năm')),
            ):
                if which == 'opening' and not check_opening:
                    continue
                if tot.get(na_key):
                    continue
                detail_sum = 0.0
                for dcode in detail_codes:
                    drow = computed.get(dcode) or {}
                    # N/A chi tiết tính 0 — đúng case «chi tiết trống / lệch tổng»
                    if drow.get(na_key):
                        continue
                    detail_sum = float_round(
                        detail_sum + (drow.get(amt_key) or 0.0), 2,
                    )
                total_amt = tot.get(amt_key) or 0.0
                diff = float_round(detail_sum - total_amt, 2)
                if float_is_zero(diff, 2):
                    continue
                detail_sum_rows.append({
                    'total_code': total_code,
                    'source_label': source_label,
                    'column': which,
                    'detail_sum': detail_sum,
                    'total_amt': total_amt,
                    'diff': diff,
                    'details': list(detail_codes),
                })
                table_warns.append(_(
                    'LƯỚI B09: bảng %(total)s — tổng chi tiết (%(dsum)s) khác '
                    'dòng tổng lấy từ %(src)s (%(tamt)s) ở cột %(col)s; '
                    'lệch = %(diff)s (chi tiết − tổng). Vẫn in.',
                    total=total_code,
                    dsum='{:,.0f}'.format(detail_sum),
                    src=source_label,
                    tamt='{:,.0f}'.format(total_amt),
                    col=col_lbl,
                    diff='{:,.0f}'.format(diff),
                ))

        if line_cmds:
            self._create_snapshot_lines_one_insert(line_cmds)

        # Cảnh báo tổng hợp ngắn — trạng thái chi tiết nằm trên từng mục bảng
        status_counts = {}
        for rl in lines_def:
            st = rl.b09_table_status
            if st:
                status_counts[st] = status_counts.get(st, 0) + 1
        short_bits = []
        if status_counts.get('total_ok_detail_open'):
            short_bits.append(_(
                '%(n)s bảng: máy đã điền tổng, chi tiết còn mở (xem trạng thái tại mục)',
                n=status_counts['total_ok_detail_open'],
            ))
        if status_counts.get('none_yet'):
            short_bits.append(_(
                '%(n)s bảng: máy chưa lấy được số (xem ghi chú tại mục)',
                n=status_counts['none_yet'],
            ))
        if status_counts.get('manual_all'):
            short_bits.append(_(
                '%(n)s mục: kế toán tự điền toàn bộ',
                n=status_counts['manual_all'],
            ))
        if short_bits:
            table_warns.append(_('B09 — ') + '; '.join(short_bits) + '.')

        empty_n, unconf_n = self.env['vas.b09.entry'].count_pending(
            self.company_id, self.period_from_id, self.period_to_id,
        )
        if empty_n:
            table_warns.append(_(
                'B09 người điền: còn %(n)s mục trống (đoạn văn / số / bảng). '
                'Không chặn lập báo cáo.',
                n=empty_n,
            ))
        if unconf_n:
            table_warns.append(_(
                'B09 người điền: %(n)s mục là gợi ý máy hoặc chép năm trước '
                'chưa được kế toán xác nhận. Không chặn lập báo cáo.',
                n=unconf_n,
            ))

        warn_parts = []
        if b01a_snap.ledger_changed and b01a_snap.ledger_stale_message:
            warn_parts.append(_(
                'Nguồn B01a đã lập có thể cũ so với sổ:\n%s',
                b01a_snap.ledger_stale_message,
            ))
        if b02_snap.ledger_changed and b02_snap.ledger_stale_message:
            warn_parts.append(_(
                'Nguồn B02 đã lập có thể cũ so với sổ:\n%s',
                b02_snap.ledger_stale_message,
            ))
        if b01a_snap.hide_reversed != self.hide_reversed:
            warn_parts.append(_(
                'Bản B01a nguồn (ẩn đảo=%(s)s) khác tùy chọn B09 (ẩn đảo=%(b)s).',
                s=b01a_snap.hide_reversed, b=self.hide_reversed,
            ))
        if b02_snap.hide_reversed != self.hide_reversed:
            warn_parts.append(_(
                'Bản B02 nguồn (ẩn đảo=%(s)s) khác tùy chọn B09 (ẩn đảo=%(b)s).',
                s=b02_snap.hide_reversed, b=self.hide_reversed,
            ))
        warn_parts.extend(table_warns)

        warning = '\n'.join(warn_parts) if warn_parts else False
        warning_level = 'danger' if danger else ('warning' if warning else False)

        self.write({
            'warning_text': warning or False,
            'warning_level': warning_level or False,
            'meta_json': json.dumps({
                'source_b01a_snapshot_id': b01a_snap.id,
                'source_b02_snapshot_id': b02_snap.id,
                'source_b01a_date_computed': fields.Datetime.to_string(
                    b01a_snap.date_computed,
                ),
                'source_b02_date_computed': fields.Datetime.to_string(
                    b02_snap.date_computed,
                ),
                'source_b01a_ledger_changed': bool(b01a_snap.ledger_changed),
                'source_b02_ledger_changed': bool(b02_snap.ledger_changed),
                'b09_source_grid': grid_rows,
                'b09_table_status_counts': status_counts,
                'b09_detail_sum_checks': detail_sum_rows,
                'b09_manual_empty_count': empty_n,
                'b09_manual_unconfirmed_count': unconf_n,
            }, ensure_ascii=False, default=str),
        })
        return True

    def _create_snapshot_lines_one_insert(self, vals_list):
        """Một câu INSERT mọi dòng — tránh ``INSERT_BATCH_SIZE=100`` của ORM."""
        from odoo.tools import SQL

        Line = self.env['vas.report.snapshot.line']
        if not vals_list:
            return Line
        uid = self.env.uid
        now = fields.Datetime.now()
        columns = (
            'snapshot_id', 'report_line_id', 'sequence', 'code', 'name',
            'line_role', 'amount_opening', 'amount_increase', 'amount_decrease',
            'amount_closing',
            'is_na_opening', 'is_na_increase', 'is_na_decrease', 'is_na_closing',
            'show_negative_paren',
            'aggregate_by_partner',
            'b09_fill_kind', 'b09_gap_reason',
            'b09_table_status', 'b09_table_status_note', 'b09_text_value',
            'b09_table_json', 'b09_value_source',
            'b09_is_from_prior', 'b09_is_confirmed',
            'create_uid', 'write_uid', 'create_date', 'write_date',
        )
        row_sqls = []
        for v in vals_list:
            row_sqls.append(SQL(
                '(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
                '%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                v['snapshot_id'],
                v.get('report_line_id') or None,
                int(v.get('sequence') or 10),
                v['code'],
                v['name'],
                v.get('line_role') or 'detail',
                float(v.get('amount_opening') or 0.0),
                float(v.get('amount_increase') or 0.0),
                float(v.get('amount_decrease') or 0.0),
                float(v.get('amount_closing') or 0.0),
                bool(v.get('is_na_opening')),
                bool(v.get('is_na_increase', True)),
                bool(v.get('is_na_decrease', True)),
                bool(v.get('is_na_closing')),
                bool(v.get('show_negative_paren')),
                bool(v.get('aggregate_by_partner')),
                v.get('b09_fill_kind') or None,
                v.get('b09_gap_reason') or None,
                v.get('b09_table_status') or None,
                v.get('b09_table_status_note') or None,
                v.get('b09_text_value') or None,
                v.get('b09_table_json') or None,
                v.get('b09_value_source') or 'empty',
                bool(v.get('b09_is_from_prior')),
                bool(v.get('b09_is_confirmed', True)),
                uid,
                uid,
                now,
                now,
            ))
        self.env.cr.execute(SQL(
            'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
            SQL.identifier(Line._table),
            SQL(', ').join(SQL.identifier(c) for c in columns),
            SQL(', ').join(row_sqls),
        ))
        ids = [row[0] for row in self.env.cr.fetchall()]
        Line.invalidate_model()
        return Line.browse(ids)

    def _related_codes_for_parent(self, parent_acc, lines_def, acc_by_code):
        tree = {parent_acc.code}
        Account = self.env['vas.account']
        children = Account.search([('parent_id', '=', parent_acc.id)])
        stack = list(children)
        while stack:
            child = stack.pop()
            tree.add(child.code)
            stack.extend(Account.search([('parent_id', '=', child.id)]))
        related = []
        for line in lines_def:
            codes = self.env['vas.report.line']._parse_codes(line.account_codes)
            if any(c in tree for c in codes):
                related.append(line.code)
        return sorted(set(related), key=lambda c: (len(c), c))

    def _build_warning_text(
        self, missing_map, total_na_map, class_warnings, opposite_msgs,
        orphan_msgs, imbalance,
    ):
        parts = []
        if missing_map:
            bits = [
                _('Chỉ tiêu %(code)s thiếu tài khoản: %(accs)s',
                  code=code, accs=', '.join(accs))
                for code, accs in sorted(missing_map.items())
            ]
            parts.append(_('THIẾU TÀI KHOẢN — không lấy số 0 im lặng:\n') + '\n'.join(bits))
        if total_na_map:
            bits = [
                _('Chỉ tiêu tổng %(code)s không tính được vì chỉ tiêu con N/A: %(ch)s',
                  code=code, ch=', '.join(children))
                for code, children in sorted(total_na_map.items())
            ]
            parts.append(_('TỔNG THIẾU CON — chỉ tiêu tổng ra N/A:\n') + '\n'.join(bits))
        if opposite_msgs:
            parts.append(
                _('DƯ NGƯỢC CHIỀU — chỉ tiêu lấy một bên nhưng TK dư bên kia '
                  '(không tự đảo / không tự xếp):\n')
                + '\n'.join(opposite_msgs)
            )
        if orphan_msgs:
            parts.append(
                _('CÔNG NỢ KHÔNG ĐỐI TÁC — không tự xếp vào chỉ tiêu:\n')
                + '\n'.join(orphan_msgs)
            )
        if imbalance is not None:
            parts.append(_(
                'CẢNH BÁO ĐẬM — Tổng tài sản (200) khác tổng nguồn vốn (500). '
                'Lệch = %(d)s (200 − 500). Báo cáo vẫn hiển thị.',
                d='{:,.0f}'.format(imbalance),
            ))
        if class_warnings:
            parts.append(_('CẢNH BÁO PHÂN LOẠI / GHI CHÚ:\n') + '\n'.join(class_warnings))
        return '\n\n'.join(parts)

    def get_report_data(self):
        """Chỉ ĐỌC bản đã lưu — tuyệt đối không quét sổ."""
        self.ensure_one()
        # refresh stale message (lightweight move search_count only)
        self._compute_ledger_changed()
        warn_parts = []
        if self.ledger_stale_message:
            warn_parts.append(self.ledger_stale_message)
        if self.warning_text:
            warn_parts.append(self.warning_text)
        warning = '\n\n'.join(warn_parts) if warn_parts else False
        warning_level = self.warning_level or (
            'warning' if self.ledger_changed else False
        )
        if self.imbalance_200_500 and not float_is_zero(self.imbalance_200_500, 2):
            warning_level = 'danger'
        if (
            self.form_code == 'B03-DNN'
            and (
                (self.check_b03_l1_diff and not float_is_zero(self.check_b03_l1_diff, 2))
                or (self.check_b03_l2_diff and not float_is_zero(self.check_b03_l2_diff, 2))
                or (self.check_b03_l4_diff and not float_is_zero(self.check_b03_l4_diff, 2))
            )
        ):
            warning_level = 'danger'

        lines_out = []
        for row in self.line_ids.sorted(lambda l: (l.sequence, l.code)):
            level = 0
            if row.line_role == 'detail' and row.code not in (
                '110', '120', '130', '140', '150', '160', '170', '180',
                '200', '300', '400', '500',
            ):
                level = 1
            if row.b09_text_value:
                opening = row.b09_text_value
                increase = row.b09_text_value
                decrease = row.b09_text_value
                closing = row.b09_text_value
            else:
                opening = 'N/A' if row.is_na_opening else row.amount_opening
                increase = (
                    'N/A' if row.is_na_increase else row.amount_increase
                )
                decrease = (
                    'N/A' if row.is_na_decrease else row.amount_decrease
                )
                closing = 'N/A' if row.is_na_closing else row.amount_closing
            label = row.name
            if self.form_code == 'B09-DNN':
                values = [row.code, label, opening, increase, decrease, closing]
            elif self.form_code in ('B01a-DNN', 'B02-DNN'):
                values = [
                    row.code, label, row.note_b09_code or '', opening, closing,
                ]
            else:
                values = [row.code, label, opening, closing]
            lines_out.append({
                'id': 'snap_%s' % row.id,
                'snapshot_line_id': row.id,
                'label': label,
                'level': level,
                'values': values,
                'unfoldable': False,
                'unfolded': False,
                'parent_id': False,
                'is_total': row.line_role == 'total' or row.code in ('200', '500'),
                'is_leaf': row.line_role == 'detail',
                'class': (
                    'o_vas_report_total' if row.code in ('200', '500')
                    else ('fw-bold' if row.line_role == 'total' else '')
                ),
                'show_negative_paren': row.show_negative_paren,
                'note_b09_code': row.note_b09_code or False,
                'b09_fill_kind': row.b09_fill_kind or False,
                'b09_gap_reason': row.b09_gap_reason or False,
                'b09_table_status': row.b09_table_status or False,
                'b09_table_status_note': row.b09_table_status_note or False,
            })

        stored_meta = {}
        if self.meta_json:
            try:
                stored_meta = json.loads(self.meta_json)
            except (TypeError, ValueError):
                stored_meta = {}

        return {
            'meta': {
                'title': self.env['vas.report.engine'].fs_form_title(self.form_code),
                'form_code': self.form_code,
                'company_name': self.company_id.name or '',
                'period_label': _(
                    'Kỳ báo cáo: từ %(a)s đến %(b)s',
                    a=self.period_from_id.name,
                    b=self.period_to_id.name,
                ),
                'currency_id': self.currency_id.id,
                'warning': warning,
                'warning_level': warning_level,
                'snapshot_id': self.id,
                'date_computed': fields.Datetime.to_string(self.date_computed),
                'is_submitted': self.is_submitted,
                'ledger_changed': self.ledger_changed,
                'missing_accounts': stored_meta.get('missing_accounts') or {},
                'total_na_children': stored_meta.get('total_na_children') or {},
                'requires_account': False,
                'from_snapshot': True,
            },
            'columns': (
                [
                    {
                        'name': 'code', 'label': 'Mã số', 'type': 'string',
                        'align': 'left', 'display': 'note_ref',
                    },
                    {
                        'name': 'name', 'label': 'Chỉ tiêu', 'type': 'string',
                        'align': 'left',
                    },
                    {
                        'name': 'opening', 'label': 'Số đầu năm',
                        'type': 'monetary', 'align': 'right',
                        'negative_paren': True,
                    },
                    {
                        'name': 'increase', 'label': 'Tăng trong năm',
                        'type': 'monetary', 'align': 'right',
                        'negative_paren': True,
                    },
                    {
                        'name': 'decrease', 'label': 'Giảm trong năm',
                        'type': 'monetary', 'align': 'right',
                        'negative_paren': True,
                    },
                    {
                        'name': 'closing', 'label': 'Số cuối kỳ',
                        'type': 'monetary', 'align': 'right',
                        'negative_paren': True,
                    },
                ] if self.form_code == 'B09-DNN' else (
                    [
                        {
                            'name': 'code', 'label': 'Mã số', 'type': 'string',
                            'align': 'left',
                        },
                        {
                            'name': 'name', 'label': 'Chỉ tiêu', 'type': 'string',
                            'align': 'left',
                        },
                        {
                            'name': 'note_b09', 'label': 'Thuyết minh',
                            'type': 'string', 'align': 'left',
                            'display': 'note_ref',
                        },
                        {
                            'name': 'opening', 'label': 'Số đầu năm',
                            'type': 'monetary', 'align': 'right',
                            'negative_paren': True,
                        },
                        {
                            'name': 'closing', 'label': 'Số cuối kỳ',
                            'type': 'monetary', 'align': 'right',
                            'negative_paren': True,
                        },
                    ] if self.form_code in ('B01a-DNN', 'B02-DNN') else [
                        {
                            'name': 'code', 'label': 'Mã số', 'type': 'string',
                            'align': 'left',
                        },
                        {
                            'name': 'name', 'label': 'Chỉ tiêu', 'type': 'string',
                            'align': 'left',
                        },
                        {
                            'name': 'opening', 'label': 'Số đầu năm',
                            'type': 'monetary', 'align': 'right',
                            'negative_paren': True,
                        },
                        {
                            'name': 'closing', 'label': 'Số cuối kỳ',
                            'type': 'monetary', 'align': 'right',
                            'negative_paren': True,
                        },
                    ]
                )
            ),
            'lines': lines_out,
            'options': {
                'company_id': self.company_id.id,
                'period_from_id': self.period_from_id.id,
                'period_to_id': self.period_to_id.id,
                'hide_reversed': self.hide_reversed,
                'snapshot_id': self.id,
            },
            'checks': {
                'imbalance_200_500': (
                    self.imbalance_200_500
                    if not float_is_zero(self.imbalance_200_500, 2) else None
                ),
                'check_60_4212_diff': (
                    self.check_60_4212_diff
                    if self.form_code == 'B02-DNN'
                    and not float_is_zero(self.check_60_4212_diff, 2)
                    else None
                ),
                'check_60_b01a_417_diff': (
                    self.check_60_b01a_417_diff
                    if self.form_code == 'B02-DNN'
                    and not float_is_zero(self.check_60_b01a_417_diff, 2)
                    else None
                ),
                'check_b03_l1_diff': (
                    self.check_b03_l1_diff
                    if self.form_code == 'B03-DNN'
                    and not float_is_zero(self.check_b03_l1_diff, 2)
                    else None
                ),
                'check_b03_l2_diff': (
                    self.check_b03_l2_diff
                    if self.form_code == 'B03-DNN'
                    and not float_is_zero(self.check_b03_l2_diff, 2)
                    else None
                ),
                'check_b03_l4_diff': (
                    self.check_b03_l4_diff
                    if self.form_code == 'B03-DNN'
                    and not float_is_zero(self.check_b03_l4_diff, 2)
                    else None
                ),
                'missing_accounts': stored_meta.get('missing_accounts') or {},
                'total_na_children': stored_meta.get('total_na_children') or {},
                'orphan_partner_msgs': stored_meta.get('orphan_partner_msgs') or [],
                'opposite_side_msgs': stored_meta.get('opposite_side_msgs') or [],
                'from_snapshot': True,
                'snapshot_id': self.id,
            },
        }


class VasReportSnapshotLine(models.Model):
    _name = 'vas.report.snapshot.line'
    _description = 'Dòng chỉ tiêu bản BCTC đã lập'
    _order = 'sequence, code, id'

    snapshot_id = fields.Many2one(
        'vas.report.snapshot', required=True, ondelete='cascade', index=True,
    )
    report_line_id = fields.Many2one('vas.report.line', ondelete='set null', index=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    line_role = fields.Selection(
        selection=[('detail', 'Chi tiết'), ('total', 'Tổng')],
        required=True,
        default='detail',
    )
    amount_opening = fields.Float(string='Số đầu năm')
    amount_increase = fields.Float(string='Tăng trong năm')
    amount_decrease = fields.Float(string='Giảm trong năm')
    amount_closing = fields.Float(string='Số cuối kỳ')
    is_na_opening = fields.Boolean(default=False)
    is_na_increase = fields.Boolean(default=True)
    is_na_decrease = fields.Boolean(default=True)
    is_na_closing = fields.Boolean(default=False)
    show_negative_paren = fields.Boolean(default=False)
    aggregate_by_partner = fields.Boolean(default=False)
    note_b09_code = fields.Char(
        string='Thuyết minh (mã mục B09)',
        help='Mã mục B09 ổn định — cột Thuyết minh trên B01a/B02.',
    )
    b09_fill_kind = fields.Selection(
        selection=B09_FILL_KIND_SELECTION,
        string='Phân loại điền B09',
    )
    b09_gap_reason = fields.Char(string='Thiếu gì (B09)')
    b09_table_status = fields.Selection(
        selection=B09_TABLE_STATUS_SELECTION,
        string='Trạng thái bảng B09',
    )
    b09_table_status_note = fields.Char(string='Ghi chú trạng thái bảng B09')
    b09_text_value = fields.Text(
        string='Nội dung text B09',
        help='Ô thuyết minh dạng chữ / đoạn văn — bản đã lập (chép từ kho người điền).',
    )
    b09_table_json = fields.Text(
        string='Bảng người điền (JSON)',
        help='Snapshot các dòng bảng lúc lập — không sửa qua đây khi đã nộp.',
    )
    b09_value_source = fields.Selection(
        selection=B09_VALUE_SOURCE_SELECTION,
        string='Nguồn số/nội dung B09',
        help='Phân biệt máy từ sổ / máy từ B01a·B02 / người khai / gợi ý chưa xác nhận.',
    )
    b09_is_from_prior = fields.Boolean(string='Chép từ năm trước')
    b09_is_confirmed = fields.Boolean(string='Đã xác nhận', default=True)
    detail_ids = fields.One2many(
        'vas.report.snapshot.detail', 'snapshot_line_id', string='Chi tiết TK/đối tác',
    )

    def write(self, vals):
        if any(l.snapshot_id.is_submitted for l in self):
            raise UserError(_('Bản đã nộp — không được sửa dòng chỉ tiêu.'))
        return super().write(vals)

    def unlink(self):
        if not self:
            return super().unlink()
        if self.env.context.get('_vas_snapshot_purge'):
            return super().unlink()
        raise UserError(_(
            'Không xóa từng dòng chỉ tiêu của bản đã lập. '
            'Xóa cả bản báo cáo hoặc lập lại.'
        ))


class VasReportSnapshotDetail(models.Model):
    _name = 'vas.report.snapshot.detail'
    _description = 'Chi tiết TK/đối tác góp vào chỉ tiêu đã lập'
    _order = 'account_code, partner_id, id'

    snapshot_line_id = fields.Many2one(
        'vas.report.snapshot.line', required=True, ondelete='cascade', index=True,
    )
    account_id = fields.Many2one('vas.account', ondelete='set null', index=True)
    account_code = fields.Char(required=True, index=True)
    partner_id = fields.Many2one('res.partner', ondelete='set null', index=True)
    amount_opening = fields.Float(string='Đầu năm')
    amount_closing = fields.Float(string='Cuối kỳ')

    def write(self, vals):
        if any(d.snapshot_line_id.snapshot_id.is_submitted for d in self):
            raise UserError(_('Bản đã nộp — không được sửa chi tiết chỉ tiêu.'))
        return super().write(vals)

    def unlink(self):
        if not self:
            return super().unlink()
        if self.env.context.get('_vas_snapshot_purge'):
            return super().unlink()
        raise UserError(_(
            'Không xóa chi tiết chỉ tiêu của bản đã lập. '
            'Xóa cả bản báo cáo hoặc lập lại.'
        ))
