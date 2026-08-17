# -*- coding: utf-8 -*-
"""Kỳ tính giá thành — Chặng 1A cấu trúc + Chặng 3 luồng nhận/tính/duyệt/ghi sổ."""
import hashlib
import json
from datetime import datetime, time

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero

from .vas_costing_flow import GROUP_A_TYPES


class VasCostingPeriod(models.Model):
    _name = 'vas.costing.period'
    _description = 'Kỳ tính giá thành'
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Tên', required=True)
    date_from = fields.Date(string='Từ ngày', required=True, index=True)
    date_to = fields.Date(string='Đến ngày', required=True, index=True)
    method = fields.Selection(
        selection=[
            ('simple', 'Giản đơn'),
            ('stepwise', 'Phân bước'),
        ],
        string='Phương pháp',
        required=True,
        default='simple',
        help='Phân bước: chỉ chừa cấu trúc — không tạo kỳ chạy thật trong đợt này.',
    )
    method_implemented = fields.Boolean(
        string='Phương pháp đã triển khai',
        compute='_compute_method_implemented',
        help='Phân bước = chưa triển khai (chỉ để trình bày trên giao diện).',
    )
    cost_object_ids = fields.Many2many(
        'vas.cost.object',
        'vas_costing_period_object_rel',
        'period_id',
        'object_id',
        string='Đối tượng trong kỳ',
        ondelete='restrict',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('computed', 'Đã tính'),
            ('pending_approval', 'Chờ duyệt'),
            ('approved', 'Đã duyệt'),
            ('posted', 'Đã ghi sổ'),
            ('locked', 'Đã khóa'),
        ],
        string='Trạng thái',
        default='draft',
        required=True,
        index=True,
        copy=False,
    )
    opening_wip = fields.Monetary(
        string='Dở dang đầu kỳ', currency_field='currency_id', default=0.0,
    )
    period_incurred = fields.Monetary(
        string='Phát sinh trong kỳ', currency_field='currency_id', default=0.0,
    )
    cost_reduction = fields.Monetary(
        string='Khoản giảm giá thành', currency_field='currency_id', default=0.0,
    )
    closing_wip = fields.Monetary(
        string='Dở dang cuối kỳ', currency_field='currency_id', default=0.0,
    )
    total_cost = fields.Monetary(
        string='Giá thành trong kỳ', currency_field='currency_id', default=0.0,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        ondelete='restrict', default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Tiền tệ',
        store=True, readonly=True,
    )
    result_version_ids = fields.One2many(
        'vas.costing.result.version', 'period_id', string='Phiên bản kết quả',
    )
    current_result_id = fields.Many2one(
        'vas.costing.result.version', string='Phiên bản hiện hành',
        compute='_compute_current_result', store=True,
    )
    closing_wip_ids = fields.One2many(
        'vas.closing.wip', 'period_id', string='Bản dở dang cuối kỳ',
    )
    receive_log_ids = fields.One2many(
        'vas.allocation.receive.log', 'period_id', string='Nhật ký nhận PB',
    )
    compute_warnings = fields.Text(string='Cảnh báo khi tính', copy=False)
    posting_move_id = fields.Many2one(
        'vas.move', string='Bút toán ghi sổ hiện hành',
        ondelete='restrict', copy=False,
    )

    @api.depends('method')
    def _compute_method_implemented(self):
        for period in self:
            period.method_implemented = period.method == 'simple'

    @api.depends(
        'result_version_ids.effectiveness',
        'result_version_ids.version',
    )
    def _compute_current_result(self):
        for period in self:
            cur = period.result_version_ids.filtered(
                lambda v: v.effectiveness == 'effective',
            ).sorted(lambda v: (v.version, v.id), reverse=True)[:1]
            period.current_result_id = cur.id if cur else False

    @api.onchange('date_from', 'date_to')
    def _onchange_dates_set_name(self):
        if self.date_from and self.date_to and not self.name:
            self.name = self._default_name_from_dates(
                self.date_from, self.date_to,
            )

    @api.model
    def _default_name_from_dates(self, date_from, date_to):
        return _(
            '%(date_from)s – %(date_to)s',
            date_from=date_from.strftime('%d/%m/%Y'),
            date_to=date_to.strftime('%d/%m/%Y'),
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('method') == 'stepwise':
                raise UserError(_(
                    'Phương pháp phân bước chưa triển khai — '
                    'không tạo được kỳ chạy thật.'
                ))
            if not vals.get('name') and vals.get('date_from') and vals.get('date_to'):
                date_from = fields.Date.to_date(vals['date_from'])
                date_to = fields.Date.to_date(vals['date_to'])
                vals['name'] = self._default_name_from_dates(date_from, date_to)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('method') == 'stepwise':
            raise UserError(_(
                'Phương pháp phân bước chưa triển khai — '
                'không tạo được kỳ chạy thật.'
            ))
        if 'cost_object_ids' in vals:
            for period in self:
                if period.state != 'draft':
                    raise UserError(_(
                        'Chỉ được sửa danh sách đối tượng khi kỳ ở trạng thái Nháp.\n'
                        'Kỳ «%(name)s» đang ở trạng thái «%(state)s».\n'
                        'Việc cần làm: lùi chuỗi trạng thái về Nháp trước khi sửa đối tượng.',
                        name=period.name,
                        state=dict(period._fields['state'].selection).get(
                            period.state, period.state,
                        ),
                    ))
                # Cửa 3: nếu đang có kết quả hiệu lực mà sửa đối tượng từ nháp
                # (sau invalidate về draft) — ok; nếu còn computed bị chặn ở trên
        res = super().write(vals)
        if 'cost_object_ids' in vals:
            for period in self:
                if period.result_version_ids.filtered(
                    lambda v: v.effectiveness == 'effective',
                ):
                    period._invalidate_for_door(
                        'objects',
                        _('Cửa 3 — sửa danh sách đối tượng của kỳ.'),
                    )
        return res

    @api.constrains('date_from', 'date_to')
    def _check_date_order(self):
        for period in self:
            if (
                period.date_from
                and period.date_to
                and period.date_from > period.date_to
            ):
                raise ValidationError(_(
                    'Từ ngày phải nhỏ hơn hoặc bằng đến ngày.'
                ))

    @api.constrains('date_from', 'date_to', 'cost_object_ids', 'company_id')
    def _check_no_overlap_same_objects(self):
        for period in self:
            if (
                not period.date_from
                or not period.date_to
                or not period.cost_object_ids
            ):
                continue
            rivals = self.search([
                ('id', '!=', period.id),
                ('company_id', '=', period.company_id.id),
                ('date_from', '<=', period.date_to),
                ('date_to', '>=', period.date_from),
            ])
            for rival in rivals:
                shared = period.cost_object_ids & rival.cost_object_ids
                if not shared:
                    continue
                method_labels = dict(period._fields['method'].selection)
                raise ValidationError(_(
                    'Chồng kỳ trên cùng đối tượng.\n'
                    'Đối tượng: %(objects)s\n'
                    'Kỳ «%(name)s» (%(method)s, %(date_from)s – %(date_to)s)\n'
                    'chồng với kỳ «%(other)s» (%(omethod)s, %(odate_from)s – %(odate_to)s).\n'
                    'Hai kỳ còn hiệu lực không được chồng khoảng ngày trên cùng '
                    'một đối tượng, không phụ thuộc phương pháp.\n'
                    'Việc cần làm: chỉnh khoảng ngày hoặc danh sách đối tượng.',
                    objects=', '.join(
                        '%s — %s' % (o.code, o.name) for o in shared
                    ),
                    name=period.name,
                    method=method_labels.get(period.method, period.method),
                    date_from=period.date_from.strftime('%d/%m/%Y'),
                    date_to=period.date_to.strftime('%d/%m/%Y'),
                    other=rival.name,
                    omethod=method_labels.get(rival.method, rival.method),
                    odate_from=rival.date_from.strftime('%d/%m/%Y'),
                    odate_to=rival.date_to.strftime('%d/%m/%Y'),
                ))

    # ------------------------------------------------------------------
    # CP1 — Nhận / hoàn tác
    # ------------------------------------------------------------------

    def _assert_draft_for_receive(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                'Chỉ nhận kết quả phân bổ khi kỳ ở trạng thái Nháp.\n'
                'Kỳ «%(name)s» đang «%(state)s».\n'
                'Việc cần làm: %(next)s',
                name=self.name,
                state=dict(self._fields['state'].selection).get(self.state),
                next=self._next_rollback_hint(),
            ))

    def _next_rollback_hint(self):
        self.ensure_one()
        hints = {
            'locked': _('Không hoàn tác được — kỳ đã khóa.'),
            'posted': _('Đảo bút toán 154 sang 155 trước.'),
            'approved': _('Thu hồi hoặc hủy hiệu lực lần duyệt trước.'),
            'pending_approval': _('Rút yêu cầu duyệt.'),
            'computed': _('Hủy hiệu lực kết quả tính hiện tại.'),
            'draft': _('Hoàn tác được ngay.'),
        }
        return hints.get(self.state, '')

    def action_receive_allocation(self, result_ids=None):
        """Nhận các phần phân bổ (result records) vào kỳ — chỉ Nháp."""
        self.ensure_one()
        self._assert_draft_for_receive()
        Result = self.env['vas.allocation.result']
        if result_ids is None:
            results = Result.search([
                ('company_id', '=', self.company_id.id),
                ('cost_object_id', 'in', self.cost_object_ids.ids),
                ('run_id.state', '=', 'confirmed'),
                ('receiving_period_ids', '=', False),
            ])
        else:
            results = Result.browse(result_ids).exists()
        for run in results.mapped('run_id'):
            run._assert_source_fingerprint_fresh(_('nhận kết quả phân bổ'))
        Log = self.env['vas.allocation.receive.log']
        for res in results:
            if res.receiving_period_ids:
                raise UserError(_(
                    'Phần của đối tượng %(obj)s đã được kỳ «%(p)s» nhận.',
                    obj=res.cost_object_id.display_name,
                    p=res.receiving_period_ids[:1].display_name,
                ))
            if res.cost_object_id not in self.cost_object_ids:
                raise UserError(_(
                    'Đối tượng %(obj)s không thuộc kỳ «%(p)s».',
                    obj=res.cost_object_id.display_name, p=self.name,
                ))
            res.receiving_period_ids = [(4, self.id)]
            Log.create({
                'period_id': self.id,
                'result_id': res.id,
                'action': 'receive',
                'reason': _('Nhận kết quả phân bổ'),
            })
        if self.result_version_ids.filtered(lambda v: v.effectiveness == 'effective'):
            self._invalidate_for_door(
                'allocation',
                _('Cửa 1 — nhận thêm phần phân bổ.'),
            )
        return True

    def action_unreceive_allocation(self, reason=None, result_ids=None):
        self.ensure_one()
        if reason is None and result_ids is None:
            return self._action_open_reason_wizard('unreceive')
        if self.state == 'locked':
            raise UserError(_('Kỳ đã khóa — không hoàn tác nhận phân bổ được.'))
        if self.state == 'posted':
            raise UserError(_(
                'Kỳ đã ghi sổ — phải đảo bút toán 154 sang 155 trước.\n'
                'Bút toán: %(m)s',
                m=self.posting_move_id.display_name if self.posting_move_id else '?',
            ))
        if self.state == 'approved':
            raise UserError(_(
                'Kỳ đã duyệt — phải thu hồi duyệt trước (giữ lịch sử).'
            ))
        if self.state == 'pending_approval':
            raise UserError(_('Kỳ chờ duyệt — phải rút yêu cầu duyệt trước.'))
        if self.state == 'computed':
            raise UserError(_(
                'Kỳ đã tính — phải hủy hiệu lực kết quả tính hiện tại trước.'
            ))
        if self.state != 'draft':
            raise UserError(_(self._next_rollback_hint()))
        if not reason:
            raise UserError(_('Hoàn tác nhận bắt buộc nhập lý do.'))
        Result = self.env['vas.allocation.result']
        if result_ids:
            results = Result.browse(result_ids).exists()
        else:
            results = Result.search([('receiving_period_ids', 'in', self.ids)])
        Log = self.env['vas.allocation.receive.log']
        for res in results:
            res.receiving_period_ids = [(3, self.id)]
            Log.create({
                'period_id': self.id,
                'result_id': res.id,
                'action': 'unreceive',
                'reason': reason,
            })
        # Cửa 1: hoàn tác nhận — hết hiệu lực nếu còn kết quả
        if self.result_version_ids.filtered(lambda v: v.effectiveness == 'effective'):
            self._invalidate_for_door(
                'allocation',
                _('Cửa 1 — hoàn tác nhận phân bổ: %(r)s', r=reason),
            )
        return True

    def action_withdraw_approval_request(self):
        for period in self:
            if period.state != 'pending_approval':
                raise UserError(_('Chỉ rút yêu cầu khi kỳ đang Chờ duyệt.'))
            for ap in period.current_result_id.approval_ids.filtered(
                lambda a: a.decision == 'submitted' and a.effectiveness == 'effective',
            ):
                ap.write({
                    'decision': 'withdrawn',
                    'effectiveness': 'ineffective',
                })
            period.state = 'computed'
        return True

    def action_revoke_approval(self, reason=None):
        for period in self:
            if period.state != 'approved':
                raise UserError(_('Chỉ thu hồi duyệt khi kỳ Đã duyệt.'))
            for ap in period.current_result_id.approval_ids.filtered(
                lambda a: a.decision == 'approved' and a.effectiveness == 'effective',
            ):
                ap.write({
                    'decision': 'revoked',
                    'effectiveness': 'ineffective',
                    'reject_reason': reason or _('Thu hồi duyệt'),
                })
            period.state = 'computed'
        return True

    def action_invalidate_computation(self, reason=None):
        for period in self:
            if period.state not in ('computed', 'draft'):
                if period.state == 'pending_approval':
                    raise UserError(_('Rút yêu cầu duyệt trước khi hủy kết quả tính.'))
                if period.state in ('approved', 'posted', 'locked'):
                    raise UserError(_(period._next_rollback_hint()))
            period._invalidate_for_door(
                'allocation',
                reason or _('Hủy hiệu lực kết quả tính hiện tại.'),
            )
        return True

    # ------------------------------------------------------------------
    # Tập hợp chi phí (CP3)
    # ------------------------------------------------------------------

    def _direct_lines(self):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('account_id.code', '=like', '154%'),
            ('cost_object_id', 'in', self.cost_object_ids.ids),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        # Loại bút toán ghi tạm / ghi bù — không nhầm vào trực tiếp / giảm GT
        return lines.filtered(
            lambda l: l.move_id.source_ref not in (
                'provisional_fg', 'costing_trueup',
                'variance_pullback', 'variance_treatment',
            )
        )

    def _amount_direct_for_object(self, obj):
        lines = self._direct_lines().filtered(lambda l: l.cost_object_id == obj)
        return sum(l.debit - l.credit for l in lines)

    def _received_results(self):
        self.ensure_one()
        return self.env['vas.allocation.result'].search([
            ('receiving_period_ids', 'in', self.ids),
        ])

    def _amount_received_overhead_for_object(self, obj):
        return sum(
            self._received_results().filtered(
                lambda r: r.cost_object_id == obj,
            ).mapped('amount')
        )

    def _reduction_lines(self):
        """Khoản giảm giá thành = ghi Có 154 (phế liệu thu hồi…)."""
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('account_id.code', '=like', '154%'),
            ('credit', '>', 0),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        lines = lines.filtered(
            lambda l: not l.cost_object_id or l.cost_object_id in self.cost_object_ids
        )
        # Loại kéo về 154 (không phải khoản giảm). Giữ variance_treatment —
        # Có 154 của phiếu vượt ĐÃ GHI SỔ là khoản giảm giá thành chính thức.
        return lines.filtered(
            lambda l: l.move_id.source_ref not in (
                'provisional_fg', 'costing_trueup', 'variance_pullback',
            )
        )

    def _amount_reduction_for_object(self, obj):
        lines = self._reduction_lines().filtered(
            lambda l: l.cost_object_id == obj or not l.cost_object_id
        )
        # Phân bổ giảm không đối tượng đều — đơn giản: chỉ dòng gắn đúng obj
        lines = self._reduction_lines().filtered(lambda l: l.cost_object_id == obj)
        return sum(lines.mapped('credit'))

    def _confirmed_closing_sheet(self):
        self.ensure_one()
        sheet = self.closing_wip_ids.filtered(
            lambda s: s.state == 'confirmed' and s.kind == 'period_end',
        )[:1]
        return sheet

    # ------------------------------------------------------------------
    # Dấu vân tay (CP5)
    # ------------------------------------------------------------------

    def _fingerprint_payload_rows(self):
        """Payload chuẩn hóa — chỉ dữ liệu tham gia tính tiền. Sắp xếp ổn định."""
        self.ensure_one()
        rows = []
        for line in self._direct_lines():
            rows.append({
                'kind': 'direct',
                'source_model': 'vas.move.line',
                'source_id': line.id,
                'amount': line.debit - line.credit,
                'date': str(line.date),
                'company_id': line.company_id.id,
                'account': line.account_id.code,
                'cost_item': line.cost_item_id.code if line.cost_item_id else '',
                'cost_object': line.cost_object_id.code if line.cost_object_id else '',
                'move_state': line.move_id.state,
                'is_reversal': bool(line.move_id.is_reversal),
                'criterion': 0.0,
            })
        for res in self._received_results():
            rows.append({
                'kind': 'overhead',
                'source_model': 'vas.allocation.result',
                'source_id': res.id,
                'amount': res.amount,
                'date': str(res.run_id.date_from),
                'company_id': res.company_id.id,
                'account': '154',
                'cost_item': res.run_id.cost_item_id.code or '',
                'cost_object': res.cost_object_id.code or '',
                'move_state': res.run_id.state,
                'is_reversal': False,
                'criterion': res.criterion_value or 0.0,
            })
        for line in self._reduction_lines():
            rows.append({
                'kind': 'reduction',
                'source_model': 'vas.move.line',
                'source_id': line.id,
                'amount': -line.credit,
                'date': str(line.date),
                'company_id': line.company_id.id,
                'account': line.account_id.code,
                'cost_item': line.cost_item_id.code if line.cost_item_id else '',
                'cost_object': line.cost_object_id.code if line.cost_object_id else '',
                'move_state': line.move_id.state,
                'is_reversal': bool(line.move_id.is_reversal),
                'criterion': 0.0,
            })
        # Chỉ phiếu vượt ĐÃ GHI SỔ còn hiệu lực — nháp / đã xác nhận chưa ghi không vào
        for vline in self._posted_variance_lines():
            rows.append({
                'kind': 'variance',
                'source_model': 'vas.variance.line',
                'source_id': vline.id,
                'amount': vline.amount_confirmed,
                'date': str(self.date_to),
                'company_id': vline.company_id.id,
                'account': 'variance',
                'cost_item': vline.cost_item_id.code if vline.cost_item_id else '',
                'cost_object': vline.cost_object_id.code if vline.cost_object_id else '',
                'move_state': vline.sheet_id.state,
                'is_reversal': False,
                'criterion': 0.0,
            })
        rows.sort(key=lambda r: (
            r['kind'], r['source_model'], r['source_id'],
            r['account'], r['cost_item'], r['cost_object'],
        ))
        return rows

    def _posted_variance_lines(self):
        self.ensure_one()
        return self.env['vas.variance.line'].search([
            ('period_id', '=', self.id),
            ('line_kind', '=', 'excess'),
            ('sheet_id.state', '=', 'posted'),
        ])

    def _assert_no_blocking_variance_sheets(self):
        """Chặn tính giá thành khi còn phiếu vượt chưa ghi sổ."""
        self.ensure_one()
        blocking = self.env['vas.variance.sheet'].search([
            ('period_id', '=', self.id),
            ('state', 'in', ('draft', 'pending_responsibility', 'confirmed')),
        ])
        blocking = blocking.filtered(
            lambda s: any(
                l.line_kind == 'excess' and l.amount_confirmed
                for l in s.line_ids
            )
        )
        if not blocking:
            return
        details = []
        for sheet in blocking:
            for line in sheet.line_ids.filtered(lambda l: l.line_kind == 'excess'):
                details.append(_(
                    'Phiếu «%(s)s» · đối tượng «%(o)s» · số tiền %(a)s · trạng thái %(st)s',
                    s=sheet.display_name,
                    o=line.cost_object_id.display_name,
                    a=line.amount_confirmed,
                    st=dict(sheet._fields['state'].selection).get(sheet.state),
                ))
        raise UserError(_(
            'Ghi sổ phiếu xử lý vượt định mức trước khi tính giá thành.\n%(d)s',
            d='\n'.join(details) or ', '.join(blocking.mapped('display_name')),
        ))

    @api.model
    def _fingerprint_digest_from_rows(self, rows):
        """Hash ổn định: luôn sắp xếp rồi mới băm — thứ tự đầu vào không đổi digest."""
        ordered = sorted(rows, key=lambda r: (
            r.get('kind'), r.get('source_model'), r.get('source_id'),
            r.get('account'), r.get('cost_item'), r.get('cost_object'),
        ))
        payload = json.dumps(ordered, ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        return digest, payload

    def _compute_fingerprint(self):
        self.ensure_one()
        return self._fingerprint_digest_from_rows(self._fingerprint_payload_rows())

    def _check_fingerprint_or_invalidate(self, milestone):
        """Kiểm dấu vân tay tại mốc. Lệch → hết hiệu lực, về Nháp. Không hứa tức thời."""
        self.ensure_one()
        cur = self.current_result_id
        if not cur or cur.effectiveness != 'effective':
            return True
        digest, _payload = self._compute_fingerprint()
        if digest != cur.fingerprint:
            self._invalidate_for_door(
                'odoo_source',
                _('Cửa 4 — dữ liệu nguồn bên Odoo lệch tại mốc «%(m)s». '
                  'Dấu vân tay cũ %(old)s ≠ mới %(new)s. '
                  '(VAS chỉ phát hiện ở mốc kiểm, không phát hiện tức thời.)',
                  m=milestone, old=cur.fingerprint, new=digest),
            )
            return False
        return True

    def _invalidate_for_door(self, door, reason):
        self.ensure_one()
        for ver in self.result_version_ids.filtered(
            lambda v: v.effectiveness == 'effective',
        ):
            ver.write({
                'effectiveness': 'ineffective',
                'invalidation_door': door,
                'invalidation_reason': reason,
            })
            for ap in ver.approval_ids.filtered(
                lambda a: a.effectiveness == 'effective',
            ):
                ap.effectiveness = 'ineffective'
        if self.state != 'draft':
            self.state = 'draft'

    # ------------------------------------------------------------------
    # Engine tính (CP5) — điều kiện đầu vào
    # ------------------------------------------------------------------

    def _period_dt_bounds(self):
        self.ensure_one()
        return (
            datetime.combine(self.date_from, time.min),
            datetime.combine(self.date_to, time.max),
        )

    def _warehouse_configs(self):
        self.ensure_one()
        return self.env['vas.costing.warehouse.config']._configs_for_company(
            self.company_id,
        )

    def _fg_moves_for_product(self, product, dt_from, dt_to, configs=None):
        """Phiếu nhập TP vật lý theo bảng khai kho — một/hai bước: một chặng, lấy trọn.

        Không đoán production→internal. Chưa có dòng khai thì không tìm thấy phiếu.
        """
        Move = self.env['stock.move']
        configs = configs if configs is not None else self._warehouse_configs()
        moves = Move.browse()
        if not configs:
            return moves
        base = [
            ('company_id', '=', self.company_id.id),
            ('product_id', '=', product.id),
            ('state', '=', 'done'),
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]
        for cfg in configs:
            moves |= Move.search(base + cfg._fg_move_domain_extra())
        return moves

    def _related_stock_moves_for_costing(self):
        """Chỉ phiếu XUẤT NVL liên quan + phiếu NHẬP TP theo bảng khai kho.

        Không gom mọi phiếu kho trong kỳ. MRP chỉ dùng mềm nếu đã cài.
        """
        self.ensure_one()
        Move = self.env['stock.move']
        moves = Move.browse()
        dt_from, dt_to = self._period_dt_bounds()
        configs = self._warehouse_configs()
        product_objs = self.cost_object_ids.filtered(
            lambda o: o.object_type == 'product'
            and o.source_model == 'product.product'
            and o.source_res_id,
        )
        for obj in product_objs:
            product = self.env['product.product'].browse(obj.source_res_id).exists()
            if not product:
                continue
            moves |= self._fg_moves_for_product(product, dt_from, dt_to, configs)
            if 'mrp.production' in self.env:
                mos = self.env['mrp.production'].search([
                    ('company_id', '=', self.company_id.id),
                    ('product_id', '=', product.id),
                    ('state', '=', 'done'),
                    ('date_finished', '>=', dt_from),
                    ('date_finished', '<=', dt_to),
                ])
                raw = mos.move_raw_ids.filtered(
                    lambda m: m.state == 'done'
                    and dt_from <= fields.Datetime.to_datetime(m.date) <= dt_to
                )
                moves |= raw
        return moves

    def _fg_receipt_stock_value_for_object(self, obj):
        """Giá trị phiếu nhập TP vật lý (Odoo) — chỉ lưới kiểm, không dùng ghi 155."""
        if (
            obj.object_type != 'product'
            or obj.source_model != 'product.product'
            or not obj.source_res_id
        ):
            return 0.0
        product = self.env['product.product'].browse(obj.source_res_id).exists()
        if not product:
            return 0.0
        dt_from, dt_to = self._period_dt_bounds()
        fg = self._fg_moves_for_product(product, dt_from, dt_to)
        Sync = self.env['vas.sync']
        return sum(abs(Sync._cogs_amount(m) or 0.0) for m in fg)

    def _warehouses_missing_config(self):
        """Kho đã có phiếu TP liên quan nhưng chưa khai bảng — không đoán mặc định."""
        self.ensure_one()
        configs = self._warehouse_configs()
        configured = configs.mapped('warehouse_id')
        dt_from, dt_to = self._period_dt_bounds()
        missing = self.env['stock.warehouse']
        product_objs = self.cost_object_ids.filtered(
            lambda o: o.object_type == 'product'
            and o.source_model == 'product.product'
            and o.source_res_id,
        )
        if not product_objs:
            return missing
        # Mọi kho công ty có thể nhận TP — bắt buộc có dòng khai trước khi ghi sổ
        company_wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id),
        ])
        if not configs:
            return company_wh
        # Phiếu TP tìm theo cấu hình đã có; thêm kho xuất hiện trên move sản phẩm
        # mà chưa nằm trong bảng khai
        Move = self.env['stock.move']
        for obj in product_objs:
            product = self.env['product.product'].browse(obj.source_res_id).exists()
            if not product:
                continue
            # Mọi move done vào internal của kho công ty trong kỳ (để phát hiện kho thiếu khai)
            cand = Move.search([
                ('company_id', '=', self.company_id.id),
                ('product_id', '=', product.id),
                ('state', '=', 'done'),
                ('date', '>=', dt_from),
                ('date', '<=', dt_to),
                ('location_dest_id.usage', '=', 'internal'),
            ])
            for move in cand:
                wh = (
                    move.picking_type_id.warehouse_id
                    or move.location_dest_id.warehouse_id
                )
                if wh and wh.company_id == self.company_id and wh not in configured:
                    missing |= wh
        return missing

    def _assert_warehouse_configs_for_post(self):
        self.ensure_one()
        product_objs = self.cost_object_ids.filtered(
            lambda o: o.object_type == 'product',
        )
        if not product_objs:
            return
        missing = self._warehouses_missing_config()
        configs = self._warehouse_configs()
        if not configs:
            whs = self.env['stock.warehouse'].search([
                ('company_id', '=', self.company_id.id),
            ])
            raise UserError(_(
                'Chặn ghi 154 sang 155: chưa khai bảng cấu hình kho giá thành.\n'
                'Kho cần khai: %(wh)s.\n'
                'Không đoán loại phiếu / khu vực — mở Connecta VAS > Cấu hình kho giá thành.',
                wh=', '.join(whs.mapped('display_name')) or _('(không có kho)'),
            ))
        if missing:
            raise UserError(_(
                'Chặn ghi 154 sang 155: còn kho chưa khai cấu hình giá thành.\n'
                'Kho: %(wh)s.\n'
                'Khai loại phiếu nhập thành phẩm và khu vực kho trước khi ghi sổ.',
                wh=', '.join(missing.mapped('display_name')),
            ))

    def _is_stock_move_unvalued(self, move):
        """True = chưa định giá. False = đã định giá (kể cả giá trị thật = 0 có chủ đích).

        Tập phiếu đã thu hẹp theo bảng khai kho. ``value=0`` + không ``product.value``
        = chưa định giá. Có ``product.value`` (kể cả 0) = đã định giá có chủ đích (W5).
        """
        if move.state != 'done':
            return False
        qty = move.quantity or move.product_uom_qty or 0.0
        if float_is_zero(qty, precision_digits=6):
            return False
        ProductValue = self.env.get('product.value')
        if ProductValue is not None and 'move_id' in ProductValue._fields:
            if ProductValue.sudo().search_count([('move_id', '=', move.id)]):
                return False
        amount = abs(self.env['vas.sync']._cogs_amount(move) or 0.0)
        if amount > 0:
            return False
        return True

    def _collect_missing_allocation_config(self):
        """Khoản mục có tiền thiếu đối tượng mà chưa có cấu hình PB — không tự chia."""
        self.ensure_one()
        bare = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('account_id.code', '=like', '154%'),
            ('cost_object_id', '=', False),
            ('cost_item_id', '!=', False),
            ('cost_item_id.code', '!=', 'CPD'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        Config = self.env['vas.allocation.config']
        missing = {}
        for line in bare:
            item = line.cost_item_id
            cfg = Config.search([
                ('active', '=', True),
                ('company_id', '=', self.company_id.id),
                ('cost_item_id', '=', item.id),
                ('date_from', '<=', self.date_to),
                '|', ('date_to', '=', False), ('date_to', '>=', self.date_from),
            ], limit=1)
            if not cfg:
                missing.setdefault(item.id, [item, 0, 0.0])
                missing[item.id][1] += 1
                missing[item.id][2] += line.debit - line.credit
        return missing

    def _missing_allocation_snapshot(self, missing):
        return '\n'.join(
            '- %s: %s dòng, số tiền %s' % (v[0].code, v[1], v[2])
            for v in missing.values()
        )

    def _warn_missing_criterion_sources(self):
        """Điều kiện 4: tiêu thức khai phải có nguồn số — cảnh báo, không chặn."""
        self.ensure_one()
        Config = self.env['vas.allocation.config']
        configs = Config.search([
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
            ('date_from', '<=', self.date_to),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date_from),
        ])
        warnings = []
        Run = self.env['vas.allocation.run']
        for cfg in configs:
            if cfg.criterion in ('manual_factor', 'named'):
                factors = cfg.factor_ids.filtered(
                    lambda f: not float_is_zero(f.factor, precision_digits=10)
                )
                if not factors:
                    warnings.append(_(
                        'Cảnh báo tiêu thức: cấu hình «%(c)s» (%(crit)s) không có '
                        'hệ số / nguồn số khác 0.',
                        c=cfg.display_name, crit=cfg.criterion,
                    ))
                continue
            # Tiêu thức máy: kiểm trọng số trên đối tượng ứng viên
            dummy = Run.new({
                'company_id': cfg.company_id.id,
                'cost_item_id': cfg.cost_item_id.id,
                'scope_type': cfg.scope_type,
                'scope_object_id': cfg.scope_object_id.id if cfg.scope_object_id else False,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'round_number': str(cfg.sequence),
                'money_source': 'pool_154' if cfg.sequence == 1 else 'prior_round',
            })
            try:
                weights = dummy._collect_objects_with_weights(cfg)
            except Exception:  # noqa: BLE001 — cảnh báo, không chặn tính
                weights = {}
            if not weights or all(
                float_is_zero(w, precision_digits=10) for w in weights.values()
            ):
                warnings.append(_(
                    'Cảnh báo tiêu thức: cấu hình «%(c)s» tiêu thức «%(crit)s» '
                    'không có nguồn số trên mọi đối tượng ứng viên (mẫu số = 0).',
                    c=cfg.display_name, crit=cfg.criterion,
                ))
        return warnings

    def _test_mode_active(self):
        return bool(
            tools.config.get('test_enable')
            or getattr(self.env.registry, 'in_test_mode', lambda: False)()
        )

    def _precheck_compute(self):
        self.ensure_one()
        warnings = []
        # 1 — phiếu kho liên quan đã có giá trị (CHẶN) — kiểm production thật
        related = self._related_stock_moves_for_costing()
        unvalued = related.filtered(self._is_stock_move_unvalued)
        # Lối ép CHỈ TRONG TEST — cộng thêm tên, không tắt kiểm thật
        if self.env.context.get('vas_test_force_unvalued_stock') and self._test_mode_active():
            extra = self.env.context['vas_test_force_unvalued_stock']
            if isinstance(extra, str):
                extra = [extra]
            names = list(unvalued.mapped('display_name')) + list(extra)
            raise UserError(_(
                'Chặn tính giá thành: phiếu kho liên quan chưa được định giá — %(n)s.',
                n=', '.join(names),
            ))
        if unvalued:
            raise UserError(_(
                'Chặn tính giá thành: phiếu kho liên quan chưa được định giá '
                '(khác với giá trị thật = 0 đã chỉnh tay).\n'
                'Phiếu: %(n)s',
                n=', '.join(unvalued.mapped(
                    lambda m: m.reference or m.display_name or str(m.id)
                )),
            ))
        # 2 — CPD trên 154 (CHẶN)
        cpd_lines = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('account_id.code', '=like', '154%'),
            ('cost_item_id.code', '=', 'CPD'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        if cpd_lines:
            raise UserError(_(
                'Chặn tính giá thành: còn bút toán 154 gắn «Chưa phân loại» (CPD).\n'
                'Số dòng: %(n)s · Số tiền: %(a)s.\n'
                'Dòng mẫu: %(sample)s',
                n=len(cpd_lines),
                a=sum(l.debit - l.credit for l in cpd_lines),
                sample=', '.join(cpd_lines[:5].mapped('display_name')),
            ))
        # 3 — cảnh báo khoản mục thiếu đối tượng chưa cấu hình (không tự chia)
        missing = self._collect_missing_allocation_config()
        if missing:
            warnings.append(_(
                'Cảnh báo: khoản mục có tiền thiếu đối tượng chưa cấu hình phân bổ '
                '(không tự chia). Muốn để lại kỳ sau: bấm «Xác nhận để lại kỳ sau» '
                'và nhập lý do (có dấu vết).\n%(l)s',
                l=self._missing_allocation_snapshot(missing),
            ))
        # 4 — tiêu thức thiếu nguồn số (CẢNH BÁO)
        warnings.extend(self._warn_missing_criterion_sources())
        # Nguồn nối mồ côi — kiểm trực tiếp
        orphans = []
        for obj in self.cost_object_ids:
            if not obj.source_model or not obj.source_res_id:
                continue
            if obj._compute_source_status_value() == 'orphan':
                orphans.append(obj)
        if orphans:
            raise UserError(_(
                'Chặn tính giá thành: đối tượng mồ côi (kiểm trực tiếp tại thời điểm chạy):\n%(l)s',
                l='\n'.join(
                    '- %s — %s (%s,%s)' % (
                        o.code, o.name, o.source_model, o.source_res_id,
                    ) for o in orphans
                ),
            ))
        sheet = self._confirmed_closing_sheet()
        if not sheet:
            pending = self.closing_wip_ids[:1]
            raise UserError(_(
                'Chặn tính giá thành: bản dở dang cuối kỳ chưa được kế toán xác nhận.\n'
                'Bản: %(n)s · Trạng thái: %(s)s.\n'
                'Số hệ thống gợi ý — chưa được kế toán xác nhận.',
                n=pending.display_name if pending else _('(chưa có)'),
                s=pending.state if pending else '',
            ))
        return warnings, sheet

    def _action_open_reason_wizard(self, action_kind):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nhập lý do'),
            'res_model': 'vas.costing.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_period_id': self.id,
                'default_action_kind': action_kind,
            },
        }

    def action_confirm_defer_unconfigured(self, reason=None):
        """Xác nhận để lại khoản mục chưa cấu hình PB sang kỳ sau — có dấu vết."""
        self.ensure_one()
        if reason is None:
            return self._action_open_reason_wizard('defer_unconfigured')
        if not (reason or '').strip():
            raise UserError(_('Bắt buộc nhập lý do để lại kỳ sau.'))
        missing = self._collect_missing_allocation_config()
        if not missing:
            raise UserError(_('Không còn khoản mục thiếu cấu hình để để lại.'))
        self.env['vas.costing.defer.log'].create({
            'period_id': self.id,
            'reason': reason.strip(),
            'snapshot': self._missing_allocation_snapshot(missing),
            'user_id': self.env.user.id,
        })
        return True

    def action_compute_costing(self):
        for period in self:
            if period.state == 'posted':
                raise UserError(_(
                    'Kỳ đã ghi sổ — không tính lại trực tiếp được.\n'
                    'Phải đảo bút toán %(m)s trước.',
                    m=period.posting_move_id.display_name if period.posting_move_id else '?',
                ))
            if period.state == 'locked':
                raise UserError(_('Kỳ đã khóa — không tính được.'))
            if period.state not in ('draft', 'computed'):
                # Cho phép từ draft; nếu pending/approved cần lùi trước
                if period.state in ('pending_approval', 'approved'):
                    raise UserError(_(period._next_rollback_hint()))
            # Kiểm dấu vân tay trước khi tính (mốc 1) — nếu còn bản hiệu lực
            if period.current_result_id:
                period._check_fingerprint_or_invalidate('trước khi tính')
            # Chặng 4: lượt phân bổ đã nhận — nguồn lệch thì chặn tính
            for run in period._received_results().mapped('run_id'):
                run._assert_source_fingerprint_fresh(_('tính giá thành'))
            period._assert_no_blocking_variance_sheets()
            warnings, sheet = period._precheck_compute()
            opening = period.opening_wip
            direct = sum(period._direct_lines().mapped(
                lambda l: l.debit - l.credit,
            ))
            # Tránh double-count: reduction nằm trong credit của direct lines
            # Direct net đã trừ credit; tách reduction ra công thức:
            reduction = sum(period._reduction_lines().mapped('credit'))
            # Direct chỉ lấy phần nợ gắn đối tượng trừ phần đã tính là reduction
            # Đơn giản hóa: amount_direct = sum(debit-credit) trên dòng có đối tượng
            # amount_reduction riêng từ credit lines; để không trừ hai lần:
            # total = opening + direct_net + overhead - closing
            # trong đó direct_net đã gồm giảm. Báo cáo tách reduction:
            overhead = sum(period._received_results().mapped('amount'))
            closing = sheet.total_confirmed()
            # Công thức S18: opening + incurred - reduction - closing
            # incurred = direct_debits + overhead; reduction = credits
            direct_debit = sum(period._direct_lines().mapped('debit'))
            total = opening + direct_debit + overhead - reduction - closing
            # Fingerprint
            digest, payload = period._compute_fingerprint()
            # Invalidate old
            period.result_version_ids.filtered(
                lambda v: v.effectiveness == 'effective',
            ).write({
                'effectiveness': 'ineffective',
                'invalidation_door': 'allocation',
                'invalidation_reason': _('Thay bằng phiên bản tính mới.'),
            })
            ver_no = (max(period.result_version_ids.mapped('version') or [0]) + 1)
            Version = self.env['vas.costing.result.version']
            Line = self.env['vas.costing.result.line']
            ver = Version.create({
                'period_id': period.id,
                'version': ver_no,
                'effectiveness': 'effective',
                'fingerprint': digest,
                'fingerprint_payload': payload,
                'opening_wip': opening,
                'amount_direct': direct_debit,
                'amount_overhead': overhead,
                'amount_reduction': reduction,
                'closing_wip': closing,
                'total_cost': total,
            })
            for obj in period.cost_object_ids:
                d = sum(
                    period._direct_lines().filtered(
                        lambda l, o=obj: l.cost_object_id == o,
                    ).mapped('debit')
                )
                oh = period._amount_received_overhead_for_object(obj)
                red = period._amount_reduction_for_object(obj)
                cl = sum(
                    sheet.line_ids.filtered(
                        lambda l, o=obj: l.cost_object_id == o,
                    ).mapped('amount_confirmed')
                )
                # Phân bổ opening đều tạm — hoặc 0 nếu chưa nhập theo đối tượng
                op = 0.0
                tc = op + d + oh - red - cl
                stock_fg = period._fg_receipt_stock_value_for_object(obj)
                Line.create({
                    'version_id': ver.id,
                    'cost_object_id': obj.id,
                    'opening_wip': op,
                    'amount_direct': d,
                    'amount_overhead': oh,
                    'amount_reduction': red,
                    'closing_wip': cl,
                    'total_cost': tc,
                    # Mặc định giản đơn cuối kỳ: coi toàn bộ GT đã giao; phần chưa giao lưu trường riêng
                    'amount_delivered': tc,
                    'amount_undelivered': 0.0,
                    'stock_fg_receipt_value': stock_fg,
                })
            period.write({
                'opening_wip': opening,
                'period_incurred': direct_debit + overhead,
                'cost_reduction': reduction,
                'closing_wip': closing,
                'total_cost': total,
                'state': 'computed',
                'compute_warnings': '\n'.join(warnings) if warnings else False,
            })
        return True

    # ------------------------------------------------------------------
    # Duyệt (CP6)
    # ------------------------------------------------------------------

    def action_submit_approval(self):
        for period in self:
            if period.state != 'computed':
                raise UserError(_('Chỉ gửi duyệt khi kỳ Đã tính.'))
            if not period._check_fingerprint_or_invalidate('trước khi gửi duyệt'):
                raise UserError(_(
                    'Dấu vân tay lệch — kỳ đã về Nháp. Tính lại trước khi gửi duyệt.'
                ))
            ver = period.current_result_id
            if not ver:
                raise UserError(_('Không có phiên bản kết quả hiệu lực.'))
            self.env['vas.costing.approval'].create({
                'result_version_id': ver.id,
                'total_cost': ver.total_cost,
                'submitter_id': self.env.user.id,
                'decision': 'submitted',
                'effectiveness': 'effective',
            })
            period.state = 'pending_approval'
        return True

    def action_approve(self):
        if not self.env.su and not self.env.user.has_group(
            'connecta_vas.group_vas_costing_approver',
        ):
            raise AccessError(_(
                'Bạn không có quyền «Duyệt giá thành».'
            ))
        for period in self:
            if period.state != 'pending_approval':
                raise UserError(_('Chỉ duyệt khi kỳ Chờ duyệt.'))
            if not period._check_fingerprint_or_invalidate('trước khi duyệt'):
                raise UserError(_('Dấu vân tay lệch — kỳ đã về Nháp.'))
            ver = period.current_result_id
            self.env['vas.costing.approval'].create({
                'result_version_id': ver.id,
                'total_cost': ver.total_cost,
                'submitter_id': self.env.user.id,
                'reviewer_id': self.env.user.id,
                'decision': 'approved',
                'effectiveness': 'effective',
            })
            period.state = 'approved'
        return True

    def action_reject(self, reason=None):
        if reason is None:
            self.ensure_one()
            return self._action_open_reason_wizard('reject')
        if not reason:
            raise UserError(_('Từ chối bắt buộc nhập lý do.'))
        for period in self:
            if period.state != 'pending_approval':
                raise UserError(_('Chỉ từ chối khi kỳ Chờ duyệt.'))
            ver = period.current_result_id
            self.env['vas.costing.approval'].create({
                'result_version_id': ver.id,
                'total_cost': ver.total_cost,
                'reviewer_id': self.env.user.id,
                'decision': 'rejected',
                'reject_reason': reason,
                'effectiveness': 'ineffective',
            })
            period.state = 'computed'
        return True

    def action_view_approval_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lịch sử duyệt'),
            'res_model': 'vas.costing.approval',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
        }

    # ------------------------------------------------------------------
    # Ghi 154→155 (CP6) + B3
    # ------------------------------------------------------------------

    def _assert_post_conditions(self):
        self.ensure_one()
        # 0 — bảng khai kho (Chặng 4): không đoán
        self._assert_warehouse_configs_for_post()
        # 1 closing confirmed
        sheet = self._confirmed_closing_sheet()
        if not sheet:
            pending = self.closing_wip_ids[:1]
            raise UserError(_(
                'Thiếu điều kiện 1: dở dang cuối kỳ chưa xác nhận.\n'
                'Bản: %(n)s · Trạng thái: %(s)s.',
                n=pending.display_name if pending else '?',
                s=pending.state if pending else '?',
            ))
        # 2 object total == delivered + undelivered
        ver = self.current_result_id
        if not ver:
            raise UserError(_('Thiếu phiên bản kết quả hiện hành.'))
        obj_total = sum(ver.line_ids.mapped('total_cost'))
        delivered = sum(ver.line_ids.mapped('amount_delivered'))
        undelivered = sum(ver.line_ids.mapped('amount_undelivered'))
        rounding = self.currency_id.rounding or 1.0
        if float_compare(
            obj_total, delivered + undelivered, precision_rounding=rounding,
        ) != 0:
            raise UserError(_(
                'Thiếu điều kiện 2: tổng theo đối tượng (%(o)s) lệch '
                'tổng giao thành phẩm + chưa giao (%(d)s + %(u)s = %(s)s). '
                'Lệch %(diff)s.',
                o=obj_total, d=delivered, u=undelivered,
                s=delivered + undelivered, diff=obj_total - delivered - undelivered,
            ))
        # 3 current version approved + period approved
        if self.state != 'approved':
            raise UserError(_(
                'Thiếu điều kiện 3: kỳ không ở trạng thái Đã duyệt (đang %(s)s). '
                'Không dùng trạng thái thẻ S18.',
                s=self.state,
            ))
        approved = ver.approval_ids.filtered(
            lambda a: a.decision == 'approved' and a.effectiveness == 'effective',
        )
        if not approved:
            raise UserError(_(
                'Thiếu điều kiện 3: phiên bản kết quả %(v)s chưa được duyệt '
                '(hiệu lực).',
                v=ver.display_name,
            ))
        # 4 fingerprint
        if not self._check_fingerprint_or_invalidate('trước khi ghi 154 sang 155'):
            raise UserError(_(
                'Thiếu điều kiện 4: dữ liệu đầu vào đã đổi sau lần duyệt '
                '(dấu vân tay lệch) — kỳ đã về Nháp.'
            ))
        return ver

    def action_post_costing(self):
        """Ghi sổ sau duyệt.

        - Ghi cuối kỳ: 154→155 một lần (không đổi hành vi Chặng 3/4).
        - Ghi ngay: ghi bù chênh lệch 155/632 (Chặng 5).
        B3: tối đa một bút toán/phiên bản còn hiệu lực.
        """
        for period in self:
            ver = period.current_result_id
            # B3 trước điều kiện trạng thái — lần gọi thứ hai phải nhận ra đã có BT
            if ver and ver.move_id and ver.move_id.state == 'posted' \
                    and not ver.move_id.is_reversal:
                raise UserError(_(
                    'B3: phiên bản %(v)s đã có bút toán ghi sổ còn hiệu lực '
                    '(%(m)s). Không tạo thêm. Muốn ghi phiên bản khác phải đảo trước.',
                    v=ver.display_name, m=ver.move_id.display_name,
                ))
            if period.posting_move_id and period.posting_move_id.state == 'posted' \
                    and not period.posting_move_id.is_reversal:
                raise UserError(_(
                    'B3: còn bút toán ghi sổ cũ %(m)s — phải đảo trước khi ghi lại.',
                    m=period.posting_move_id.display_name,
                ))
            mode = period._assert_posting_mode_homogeneous()
            if mode == 'immediate':
                period._action_post_trueup_immediate()
                continue
            # ----- Ghi cuối kỳ (giữ nguyên Chặng 3/4) -----
            ver = period._assert_post_conditions()
            acc_154 = self.env['vas.account'].search([
                ('code', '=', '154'),
                ('regime_id', '=', period.company_id.vas_regime_id.id),
            ], limit=1)
            acc_155 = self.env['vas.account'].search([
                ('code', '=', '155'),
                ('regime_id', '=', period.company_id.vas_regime_id.id),
            ], limit=1)
            if not acc_154 or not acc_155:
                raise UserError(_('Thiếu tài khoản 154 hoặc 155.'))
            journal = self.env['vas.journal'].search([
                ('company_id', '=', period.company_id.id),
                ('type', '=', 'general'),
            ], limit=1)
            amount = ver.total_cost
            move = self.env['vas.move'].create({
                'date': period.date_to,
                'journal_id': journal.id,
                'regime_id': period.company_id.vas_regime_id.id,
                'move_kind': 'manual',
                'ref': _('GT %s', period.name),
                'company_id': period.company_id.id,
                'currency_id': period.currency_id.id,
                'line_ids': [
                    (0, 0, {
                        'account_id': acc_155.id,
                        'name': _('Giá thành %s', period.name),
                        'debit': amount if amount > 0 else 0.0,
                        'credit': -amount if amount < 0 else 0.0,
                        'currency_id': period.currency_id.id,
                    }),
                    (0, 0, {
                        'account_id': acc_154.id,
                        'name': _('Kết chuyển GT %s', period.name),
                        'debit': -amount if amount < 0 else 0.0,
                        'credit': amount if amount > 0 else 0.0,
                        'currency_id': period.currency_id.id,
                    }),
                ],
            })
            move.action_post()
            ver.move_id = move.id
            period.write({
                'posting_move_id': move.id,
                'state': 'posted',
            })
        return True

    def action_reverse_posting(self):
        for period in self:
            if period.state != 'posted':
                raise UserError(_('Chỉ đảo khi kỳ Đã ghi sổ.'))
            move = period.posting_move_id
            if not move:
                raise UserError(_('Không có bút toán để đảo.'))
            # Dùng đường đảo sẵn nếu có
            if hasattr(move, 'action_reverse'):
                move.action_reverse()
            else:
                move.write({'state': 'cancelled'})
            period.write({
                'posting_move_id': False,
                'state': 'approved',
            })
            if period.current_result_id:
                period.current_result_id.move_id = False
        return True

    def action_lock_period(self):
        for period in self:
            if period.state != 'posted':
                raise UserError(_('Chỉ khóa khi kỳ Đã ghi sổ.'))
            period.state = 'locked'
        return True

    def action_open_s18(self):
        self.ensure_one()
        ver = self.current_result_id
        if not ver:
            raise UserError(_('Chưa có phiên bản kết quả.'))
        return ver.action_open_s18()
