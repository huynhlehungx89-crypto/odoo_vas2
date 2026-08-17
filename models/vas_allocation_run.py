# -*- coding: utf-8 -*-
"""Lượt phân bổ chi phí chung + kết quả + truy vết + engine bước A (W12 Chặng 2)."""
import hashlib
import json
import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

from .vas_allocation_config import ALLOCATION_CRITERIA, ALLOCATION_SCOPES


class VasAllocationRun(models.Model):
    _name = 'vas.allocation.run'
    _description = 'Lượt phân bổ chi phí chung'
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Tên', required=True, copy=False, default='Mới')
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        ondelete='restrict',
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    date_from = fields.Date(string='Từ ngày', required=True)
    date_to = fields.Date(string='Đến ngày', required=True)
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        required=True,
        index=True,
        ondelete='restrict',
        domain="[('is_aggregate_node', '=', False), ('code', '!=', 'CPD'), "
               "('company_id', '=', company_id)]",
    )
    scope_type = fields.Selection(
        selection=ALLOCATION_SCOPES,
        string='Loại phạm vi',
        required=True,
        default='company',
        index=True,
    )
    scope_object_id = fields.Many2one(
        'vas.cost.object',
        string='Bản ghi phạm vi',
        index=True,
        ondelete='restrict',
    )
    round_number = fields.Selection(
        selection=[('1', 'Vòng 1'), ('2', 'Vòng 2')],
        string='Vòng phân bổ',
        required=True,
        default='1',
        index=True,
    )
    money_source = fields.Selection(
        selection=[
            ('pool_154', 'Thùng 154'),
            ('prior_round', 'Kết quả vòng trước'),
        ],
        string='Nguồn tiền',
        required=True,
        default='pool_154',
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('confirmed', 'Đã xác nhận'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        default='draft',
        required=True,
        index=True,
        copy=False,
    )
    version = fields.Integer(string='Phiên bản', default=1, copy=False)
    previous_run_id = fields.Many2one(
        'vas.allocation.run',
        string='Phiên bản trước',
        index=True,
        ondelete='restrict',
        copy=False,
    )
    parent_run_id = fields.Many2one(
        'vas.allocation.run',
        string='Lượt vòng một cha',
        index=True,
        ondelete='restrict',
        copy=False,
        help='B2: vòng hai phải trỏ đích danh lượt vòng một cha.',
    )
    fingerprint = fields.Char(
        string='Dấu vân tay nguồn', copy=False, index=True,
        help='Chụp khi xác nhận — phát hiện dòng chi phí chung phát sinh muộn.',
    )
    fingerprint_payload = fields.Text(string='Payload dấu vân tay', copy=False)
    needs_recompute = fields.Boolean(
        string='Cần chạy lại', default=False, copy=False, index=True,
    )
    recompute_reason = fields.Text(string='Lý do cần chạy lại', copy=False)
    config_id = fields.Many2one(
        'vas.allocation.config',
        string='Dòng cấu hình',
        ondelete='restrict',
        help='Dòng cấu hình hiệu lực dùng khi tính.',
    )
    amount_source = fields.Monetary(
        string='Tổng chi phí chung đầu vào',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    amount_allocated = fields.Monetary(
        string='Đã xác định phần đối tượng',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    amount_unallocated = fields.Monetary(
        string='Số chưa thể phân bổ',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Trạng thái tiền 1 — mẫu số = 0 hoặc thiếu nguồn số.',
    )
    amount_pending_period = fields.Monetary(
        string='Đã xác định, chưa kỳ nào nhận',
        currency_field='currency_id',
        compute='_compute_amount_period_buckets',
        help='Trạng thái tiền 2.',
    )
    amount_received = fields.Monetary(
        string='Đã được kỳ nhận',
        currency_field='currency_id',
        compute='_compute_amount_period_buckets',
        help='Trạng thái tiền 3.',
    )
    unallocated_reason = fields.Text(
        string='Nguyên nhân chưa phân bổ',
        readonly=True,
        copy=False,
    )
    compute_ok = fields.Boolean(
        string='Tính thành công',
        default=False,
        copy=False,
        help='False khi mẫu số = 0 toàn phần — không coi là thành công.',
    )
    result_ids = fields.One2many(
        'vas.allocation.result', 'run_id', string='Kết quả theo đối tượng',
    )
    trace_ids = fields.One2many(
        'vas.allocation.trace', 'run_id', string='Truy vết nguồn',
    )
    note = fields.Text(string='Ghi chú')

    @api.depends(
        'result_ids.amount',
        'result_ids.amount_received',
        'result_ids.receiving_period_ids',
    )
    def _compute_amount_period_buckets(self):
        for run in self:
            received = 0.0
            pending = 0.0
            for res in run.result_ids:
                recv = res.amount_received
                received += recv
                pending += (res.amount - recv)
            run.amount_received = received
            run.amount_pending_period = pending

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for run in self:
            if run.date_from and run.date_to and run.date_to < run.date_from:
                raise ValidationError(_(
                    'Đến ngày phải sau hoặc bằng từ ngày.'
                ))

    @api.constrains('scope_type', 'scope_object_id')
    def _check_scope(self):
        for run in self:
            if run.scope_type == 'workshop':
                raise ValidationError(_(
                    'Chưa có đường nối — không chọn được phạm vi «Theo phân xưởng».'
                ))
            if run.scope_type != 'company' and not run.scope_object_id:
                raise ValidationError(_(
                    'Phạm vi khác toàn công ty bắt buộc chọn bản ghi phạm vi.'
                ))

    @api.constrains('round_number', 'money_source')
    def _check_round_money_pair(self):
        for run in self:
            if run.round_number == '1' and run.money_source != 'pool_154':
                raise ValidationError(_(
                    'Vòng 1 phải lấy nguồn tiền từ thùng 154.'
                ))
            if run.round_number == '2' and run.money_source != 'prior_round':
                raise ValidationError(_(
                    'Vòng 2 phải lấy nguồn tiền từ kết quả vòng trước.'
                ))

    @api.constrains(
        'round_number', 'money_source', 'parent_run_id',
        'company_id', 'cost_item_id', 'scope_type', 'scope_object_id',
        'date_from', 'date_to',
    )
    def _check_parent_run_b2(self):
        """B2 — vòng hai trỏ đích danh cha; năm điều kiện."""
        for run in self:
            if run.round_number != '2':
                if run.parent_run_id:
                    raise ValidationError(_(
                        'Chỉ lượt vòng 2 mới khai lượt vòng một cha.'
                    ))
                continue
            if not run.parent_run_id:
                raise ValidationError(_(
                    'Vòng 2 bắt buộc chọn lượt vòng một cha (B2).'
                ))
            parent = run.parent_run_id
            errors = []
            if parent.state != 'confirmed':
                errors.append(_('cha không còn hiệu lực (trạng thái %(s)s)',
                                s=parent.state))
            if parent.company_id != run.company_id:
                errors.append(_('cha sai công ty'))
            if parent.cost_item_id != run.cost_item_id:
                errors.append(_('cha sai khoản mục'))
            if (
                parent.scope_type != run.scope_type
                or parent.scope_object_id != run.scope_object_id
            ):
                errors.append(_('cha sai phạm vi'))
            if parent.date_from != run.date_from or parent.date_to != run.date_to:
                errors.append(_('cha sai khoảng thời gian'))
            if parent.round_number != '1':
                errors.append(_('cha không phải vòng ngay trước'))
            if errors:
                raise ValidationError(_(
                    'Lượt vòng hai «%(name)s» không thỏa B2:\n- %(list)s',
                    name=run.display_name,
                    list='\n- '.join(errors),
                ))

    def _conflict_domain(self):
        """Khóa bảy thành phần (trừ trạng thái)."""
        self.ensure_one()
        return [
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('cost_item_id', '=', self.cost_item_id.id),
            ('scope_type', '=', self.scope_type),
            ('scope_object_id', '=', self.scope_object_id.id
             if self.scope_object_id else False),
            ('round_number', '=', self.round_number),
            ('money_source', '=', self.money_source),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
            ('state', '=', 'confirmed'),
        ]

    def _find_confirmed_conflicts(self):
        self.ensure_one()
        return self.search(self._conflict_domain())

    def _run_occupies_ceiling(self):
        """B1.2 — đóng góp còn hiệu lực chiếm trần."""
        self.ensure_one()
        if self.state == 'confirmed':
            return True
        if self.state == 'cancelled' and self.result_ids.filtered(
            lambda r: r.receiving_period_ids
        ):
            return True
        return False

    def _source_net_amount(self, source):
        if source._name == 'vas.move.line':
            return source.debit - source.credit
        return source.amount

    def _effective_contrib_for_source(self, source, exclude_run_ids=None):
        """Tổng đóng góp còn hiệu lực của một dòng nguồn, cộng chéo mọi lượt."""
        exclude_run_ids = set(exclude_run_ids or [])
        Trace = self.env['vas.allocation.trace']
        if source._name == 'vas.move.line':
            domain = [('source_move_line_id', '=', source.id)]
        else:
            domain = [('source_result_id', '=', source.id)]
        traces = Trace.search(domain)
        total = 0.0
        for tr in traces:
            if tr.run_id.id in exclude_run_ids:
                continue
            if tr.run_id._run_occupies_ceiling():
                total += tr.amount
        return total

    def _lock_source_rows(self):
        """B1.3 — khóa trước, đọc sau. Khóa theo id tăng dần."""
        self.ensure_one()
        cr = self.env.cr
        if self.round_number == '1':
            ids = sorted({
                t.source_move_line_id.id
                for t in self.trace_ids
                if t.source_move_line_id
            })
            if ids:
                cr.execute(
                    'SELECT id FROM vas_move_line WHERE id = ANY(%s) '
                    'ORDER BY id FOR UPDATE',
                    (ids,),
                )
            return ('vas.move.line', ids)
        ids = sorted({
            t.source_result_id.id
            for t in self.trace_ids
            if t.source_result_id
        })
        if ids:
            cr.execute(
                'SELECT id FROM vas_allocation_result WHERE id = ANY(%s) '
                'ORDER BY id FOR UPDATE',
                (ids,),
            )
        return ('vas.allocation.result', ids)

    def _assert_b1_ceiling(self, exclude_run_ids=None):
        """B1.1 — trần hai phía theo dấu; cùng dấu với nguồn."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 1.0
        exclude_run_ids = list(exclude_run_ids or [])
        # Nguồn theo trace của lượt này
        sources = {}
        for tr in self.trace_ids:
            src = tr.source_move_line_id or tr.source_result_id
            if not src:
                continue
            sources[src] = self._source_net_amount(src)
        # Zero-denom: không có trace — vẫn OK (không chiếm trần bằng đóng góp)
        for src, net in sources.items():
            effective = self._effective_contrib_for_source(
                src, exclude_run_ids=exclude_run_ids,
            )
            # Cộng thêm đóng góp của chính lượt này (chưa confirmed)
            mine = sum(
                t.amount for t in self.trace_ids
                if (t.source_move_line_id or t.source_result_id) == src
            )
            if self.id not in exclude_run_ids and self.state == 'draft':
                # mine chưa nằm trong effective (draft không chiếm) — cộng vào kiểm
                total = effective + mine
            else:
                total = effective
            # Cùng dấu
            for amt in (mine,) if self.state == 'draft' else ():
                if float_is_zero(amt, precision_rounding=rounding):
                    continue
                if float_compare(net, 0.0, precision_rounding=rounding) > 0 and \
                        float_compare(amt, 0.0, precision_rounding=rounding) < 0:
                    raise UserError(_(
                        'B1.1: đóng góp ngược dấu với nguồn dương '
                        '(dòng %(src)s, đóng góp %(a)s).',
                        src=src.display_name, a=amt,
                    ))
                if float_compare(net, 0.0, precision_rounding=rounding) < 0 and \
                        float_compare(amt, 0.0, precision_rounding=rounding) > 0:
                    raise UserError(_(
                        'B1.1: đóng góp ngược dấu với nguồn âm '
                        '(dòng %(src)s, đóng góp %(a)s).',
                        src=src.display_name, a=amt,
                    ))
            if float_compare(net, 0.0, precision_rounding=rounding) > 0:
                if float_compare(total, 0.0, precision_rounding=rounding) < 0 or \
                        float_compare(total, net, precision_rounding=rounding) > 0:
                    raise UserError(_(
                        'B1: vượt trần dòng nguồn dương «%(src)s»: '
                        'tổng đóng góp còn hiệu lực %(t)s ngoài [0 … %(n)s].',
                        src=src.display_name, t=total, n=net,
                    ))
            elif float_compare(net, 0.0, precision_rounding=rounding) < 0:
                if float_compare(total, net, precision_rounding=rounding) < 0 or \
                        float_compare(total, 0.0, precision_rounding=rounding) > 0:
                    raise UserError(_(
                        'B1: vượt trần dòng nguồn âm «%(src)s»: '
                        'tổng đóng góp còn hiệu lực %(t)s ngoài [%(n)s … 0].',
                        src=src.display_name, t=total, n=net,
                    ))

    def action_confirm(self):
        for run in self:
            if run.state != 'draft':
                raise UserError(_('Chỉ xác nhận được lượt đang Nháp.'))
            if not run.compute_ok and not float_is_zero(
                run.amount_source, precision_rounding=run.currency_id.rounding,
            ):
                if not run.unallocated_reason and not run.result_ids:
                    raise UserError(_(
                        'Lượt %(name)s chưa chạy tính. Bấm «Tính» trước khi xác nhận.',
                        name=run.display_name,
                    ))
            conflicts = run._find_confirmed_conflicts()
            # Phiên bản mới thay thế: bỏ qua xung đột với previous_run_id
            if run.previous_run_id:
                conflicts = conflicts.filtered(
                    lambda c: c.id != run.previous_run_id.id
                )
            if conflicts:
                raise UserError(_(
                    'Không xác nhận được lượt «%(name)s»: xung đột khóa bảy thành phần '
                    'với lượt đã xác nhận:\n%(list)s\n\n'
                    '(Công ty, khoản mục, loại phạm vi, bản ghi phạm vi, khoảng ngày, '
                    'nguồn tiền, vòng phân bổ).',
                    name=run.display_name,
                    list='\n'.join(
                        '- %s (id=%s, %s → %s)' % (
                            c.name, c.id, c.date_from, c.date_to,
                        ) for c in conflicts
                    ),
                ))
            # B1.3: khóa → đọc → kiểm → ghi (nguyên tử với thay thế phiên bản)
            exclude = []
            prev = run.previous_run_id
            if prev and prev.state == 'confirmed':
                if prev.result_ids.filtered(lambda r: r.receiving_period_ids):
                    periods = prev.result_ids.mapped('receiving_period_ids')
                    raise UserError(_(
                        'Không xác nhận phiên bản mới: phiên bản cũ còn phần đã được kỳ '
                        'nhận — %(periods)s. Hoàn tác việc nhận trước (B1.2).',
                        periods=', '.join(periods.mapped('display_name')),
                    ))
                exclude = [prev.id]
            run._lock_source_rows()
            run._assert_b1_ceiling(exclude_run_ids=exclude)
            if prev and prev.state == 'confirmed' and prev.id in exclude:
                prev.state = 'cancelled'
            digest, payload = run._compute_source_fingerprint()
            run.write({
                'state': 'confirmed',
                'fingerprint': digest,
                'fingerprint_payload': payload,
                'needs_recompute': False,
                'recompute_reason': False,
            })
        return True

    def _source_fingerprint_rows(self):
        """Payload nguồn tiền của lượt — phát hiện hóa đơn/chi phí phát sinh muộn."""
        self.ensure_one()
        rows = []
        # Dòng nguồn đã tham gia truy vết
        for tr in self.trace_ids:
            src = tr.source_move_line_id
            if src:
                rows.append({
                    'kind': 'move_line',
                    'id': src.id,
                    'amount': src.debit - src.credit,
                    'date': str(src.date),
                    'account': src.account_id.code or '',
                    'cost_item': src.cost_item_id.code if src.cost_item_id else '',
                    'move_state': src.move_id.state,
                })
            elif tr.source_result_id:
                res = tr.source_result_id
                rows.append({
                    'kind': 'prior_result',
                    'id': res.id,
                    'amount': res.amount,
                    'date': str(res.run_id.date_from),
                    'account': '154',
                    'cost_item': res.run_id.cost_item_id.code or '',
                    'move_state': res.run_id.state,
                })
        # Thùng 154 hiện tại trong khoảng ngày (cùng khoản mục, chưa đối tượng)
        # — bắt dòng phát sinh muộn chưa có trong trace
        if self.money_source == 'pool_154':
            bare = self.env['vas.move.line'].search([
                ('company_id', '=', self.company_id.id),
                ('move_id.state', '=', 'posted'),
                ('account_id.code', '=like', '154%'),
                ('cost_item_id', '=', self.cost_item_id.id),
                ('cost_object_id', '=', False),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('move_id.is_reversal', '=', False),
            ])
            for line in bare:
                rows.append({
                    'kind': 'pool_line',
                    'id': line.id,
                    'amount': line.debit - line.credit,
                    'date': str(line.date),
                    'account': line.account_id.code or '',
                    'cost_item': line.cost_item_id.code if line.cost_item_id else '',
                    'move_state': line.move_id.state,
                })
        rows.sort(key=lambda r: (r['kind'], r['id'], r['account'], r['amount']))
        return rows

    def _compute_source_fingerprint(self):
        self.ensure_one()
        rows = self._source_fingerprint_rows()
        payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        return digest, payload

    def action_check_source_fingerprint(self):
        """Quy tắc hết hiệu lực cho lượt phân bổ — đánh dấu cần chạy lại nếu lệch."""
        for run in self:
            if run.state != 'confirmed' or not run.fingerprint:
                continue
            digest, _payload = run._compute_source_fingerprint()
            if digest == run.fingerprint:
                continue
            # So sánh payload để nêu đích danh
            try:
                old_rows = json.loads(run.fingerprint_payload or '[]')
            except json.JSONDecodeError:
                old_rows = []
            new_rows = run._source_fingerprint_rows()
            old_ids = {
                (r.get('kind'), r.get('id')) for r in old_rows
            }
            new_ids = {
                (r.get('kind'), r.get('id')) for r in new_rows
            }
            added = new_ids - old_ids
            removed = old_ids - new_ids
            parts = []
            if added:
                parts.append(
                    'thêm %s dòng nguồn %s' % (
                        len(added),
                        ', '.join('%s:%s' % x for x in sorted(added)[:5]),
                    )
                )
            if removed:
                parts.append(
                    'mất %s dòng nguồn %s' % (
                        len(removed),
                        ', '.join('%s:%s' % x for x in sorted(removed)[:5]),
                    )
                )
            if not parts:
                parts.append('số tiền / trạng thái nguồn đổi (cùng tập dòng)')
            reason = _(
                'Dữ liệu nguồn lệch sau khi xác nhận lượt «%(name)s» '
                '(%(dfrom)s → %(dto)s): %(detail)s. Cần chạy lại phân bổ.',
                name=run.display_name,
                dfrom=run.date_from,
                dto=run.date_to,
                detail='; '.join(parts),
            )
            run.write({
                'needs_recompute': True,
                'recompute_reason': reason,
            })
        return True

    def _assert_not_stale_for_receive(self):
        self.ensure_one()
        self.action_check_source_fingerprint()
        if self.needs_recompute:
            raise UserError(_(
                'Không nhận kết quả phân bổ: lượt «%(r)s» cần chạy lại.\n%(reason)s',
                r=self.display_name,
                reason=self.recompute_reason or '',
            ))

    def _assert_source_fingerprint_fresh(self, for_action=None):
        """Chặn nhận / tính khi nguồn lượt lệch sau xác nhận."""
        self.ensure_one()
        self.action_check_source_fingerprint()
        if self.needs_recompute:
            raise UserError(_(
                'Không %(act)s: lượt «%(r)s» cần chạy lại.\n%(reason)s',
                act=for_action or _('tiếp tục'),
                r=self.display_name,
                reason=self.recompute_reason or '',
            ))


    def action_set_draft(self):
        """Đưa về nháp — cổng kiểm dấu vân tay nguồn (Chặng 4/5).

        Không có tín hiệu tức thời từ Odoo: so dấu tại cổng này; lệch → đánh dấu
        cần chạy lại trước khi cho về nháp / tính lại.
        """
        for run in self:
            # Cổng 2: mở lại lượt
            if run.state == 'confirmed' and run.fingerprint:
                run.action_check_source_fingerprint()
            if run.result_ids.filtered(lambda r: r.receiving_period_ids):
                periods = run.result_ids.mapped('receiving_period_ids')
                raise UserError(_(
                    'Không đưa về nháp: kết quả đã được kỳ nhận — %(periods)s. '
                    'Hoàn tác việc nhận trên kỳ đó trước (chặng sau).',
                    periods=', '.join(periods.mapped('display_name')),
                ))
            run.state = 'draft'
        return True

    def action_compute(self):
        """Tính / tính lại (bước A). Không sinh bút toán."""
        for run in self:
            run._compute_allocation(replace=True)
        return True

    def action_recompute(self):
        return self.action_compute()

    def action_new_version(self):
        """Tạo phiên bản nháp mới — B1.2: KHÔNG giải phóng trần (không hủy bản cũ)."""
        self.ensure_one()
        received = self.result_ids.filtered(lambda r: r.receiving_period_ids)
        if received:
            periods = received.mapped('receiving_period_ids')
            raise UserError(_(
                'Không tạo phiên bản mới ghi đè: kết quả đã được kỳ nhận — '
                '%(periods)s.\nHoàn tác việc nhận trên kỳ đó trước.',
                periods=', '.join(periods.mapped('display_name')),
            ))
        copy = self.copy({
            'name': _('%(name)s (v%(v)s)', name=self.name, v=self.version + 1),
            'state': 'draft',
            'version': self.version + 1,
            'previous_run_id': self.id,
            'compute_ok': False,
            'amount_source': 0.0,
            'amount_allocated': 0.0,
            'amount_unallocated': 0.0,
            'unallocated_reason': False,
        })
        # B1.2: nháp không hủy bản cũ — trần vẫn do bản confirmed giữ
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': copy.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_previous_versions(self):
        self.ensure_one()
        runs = self
        cur = self
        while cur.previous_run_id:
            runs |= cur.previous_run_id
            cur = cur.previous_run_id
        runs |= self.search([('previous_run_id', 'child_of', self.id)])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Phiên bản cũ'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'domain': [('id', 'in', runs.ids)],
        }

    def action_view_receiving_periods(self):
        self.ensure_one()
        periods = self.result_ids.mapped('receiving_period_ids')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Kỳ đã nhận kết quả của lượt này'),
            'res_model': 'vas.costing.period',
            'view_mode': 'list,form',
            'domain': [('id', 'in', periods.ids)],
        }

    # -------------------------------------------------------------------------
    # Engine — bước A
    # -------------------------------------------------------------------------

    def _compute_allocation(self, replace=True):
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_('Lượt đã hủy — không tính được.'))
        received = self.result_ids.filtered(lambda r: r.receiving_period_ids)
        if received and replace:
            periods = received.mapped('receiving_period_ids')
            raise UserError(_(
                'Không ghi đè kết quả: đã được kỳ nhận — %(periods)s.\n'
                'Hoàn tác việc nhận trên kỳ đó trước.',
                periods=', '.join(periods.mapped('display_name')),
            ))

        config = self._resolve_config()
        if not config and self.money_source == 'pool_154':
            raise UserError(_(
                'Không có dòng cấu hình phân bổ hiệu lực cho khoản mục %(item)s / '
                'phạm vi %(scope)s / vòng %(round)s trong khoảng %(a)s–%(b)s.',
                item=self.cost_item_id.display_name,
                scope=self.scope_type,
                round=self.round_number,
                a=self.date_from,
                b=self.date_to,
            ))
        self.config_id = config.id if config else False

        # Xóa kết quả cũ (chỉ khi chưa bị nhận — đã chặn ở trên)
        if replace:
            self.trace_ids.unlink()
            self.result_ids.unlink()

        source_lines, source_total = self._gather_source_lines(config)
        rounding = self.currency_id.rounding or 1.0

        if float_is_zero(source_total, precision_rounding=rounding):
            self.write({
                'amount_source': 0.0,
                'amount_allocated': 0.0,
                'amount_unallocated': 0.0,
                'unallocated_reason': _('Tổng nguồn bằng 0 — không có gì để chia.'),
                'compute_ok': True,
                'name': self._auto_run_name_if_default(),
            })
            return

        objects_weights = self._collect_objects_with_weights(config)
        # Kiểm nguồn nối trực tiếp tại thời điểm chạy
        self._assert_sources_alive(objects_weights.keys())

        positive = {
            obj: w for obj, w in objects_weights.items()
            if float_compare(w, 0.0, precision_digits=10) > 0
        }
        # Cấm âm đã chặn ở config; vẫn chặn nếu nguồn máy trả âm
        negative = {
            obj: w for obj, w in objects_weights.items()
            if float_compare(w, 0.0, precision_digits=10) < 0
        }
        if negative:
            raise UserError(_(
                'Cấm tiêu thức âm. Đối tượng: %(list)s',
                list=', '.join(
                    '%s=%s' % (o.code, w) for o, w in negative.items()
                ),
            ))

        if not positive:
            self.write({
                'amount_source': source_total,
                'amount_allocated': 0.0,
                'amount_unallocated': source_total,
                'unallocated_reason': _(
                    'Mẫu số bằng 0 toàn phần: không có đối tượng nào có tiêu thức '
                    'lớn hơn 0. Số tiền %(amount)s giữ ở trạng thái chưa phân bổ.',
                    amount=self._fmt_amount(source_total),
                ),
                'compute_ok': False,
                'name': self._auto_run_name_if_default(),
            })
            return

        shares, exact_ratios = self._allocate_by_largest_remainder(
            source_total, positive, rounding,
        )
        # Lưới khớp tuyệt đối
        allocated = sum(shares.values())
        unallocated = 0.0
        if float_compare(
            allocated + unallocated, source_total, precision_rounding=rounding,
        ) != 0:
            raise UserError(_(
                'Lưới khớp tuyệt đối thất bại: tổng đã phân bổ (%(a)s) + chưa phân bổ '
                '(%(u)s) lệch tổng nguồn (%(s)s) = %(d)s.',
                a=allocated, u=unallocated, s=source_total,
                d=allocated + unallocated - source_total,
            ))

        # Ghi kết quả theo thứ tự xác định: mã đối tượng, rồi id
        ordered = sorted(shares.keys(), key=lambda o: (o.code or '', o.id))
        Result = self.env['vas.allocation.result']
        Trace = self.env['vas.allocation.trace']
        result_map = {}
        seq = 10
        for obj in ordered:
            amt = shares[obj]
            ratio = exact_ratios[obj]
            res = Result.create({
                'run_id': self.id,
                'sequence': seq,
                'cost_object_id': obj.id,
                'amount': amt,
                'ratio': ratio,
                'criterion_value': positive[obj],
            })
            result_map[obj.id] = res
            seq += 10

        # Truy vết: chia từng dòng nguồn theo cùng tỷ lệ / largest remainder
        self._write_traces(source_lines, result_map, positive, rounding)

        # Kiểm tổng đóng góp theo từng dòng nguồn (phân bổ hết → đẳng thức chặt)
        self._assert_trace_balance(source_lines, rounding, full_allocation=True)

        self.write({
            'amount_source': source_total,
            'amount_allocated': allocated,
            'amount_unallocated': unallocated,
            'unallocated_reason': False,
            'compute_ok': True,
            'name': self._auto_run_name_if_default(),
        })

    def _default_run_name(self):
        self.ensure_one()
        return _('PB %(item)s %(a)s–%(b)s v%(v)s') % {
            'item': self.cost_item_id.code or '',
            'a': self.date_from,
            'b': self.date_to,
            'v': self.version,
        }

    def _auto_run_name_if_default(self):
        """Giữ tên người dùng đã đặt; chỉ tự đặt khi còn mặc định."""
        self.ensure_one()
        if not self.name or self.name in ('Mới', 'New'):
            return self._default_run_name()
        return self.name

    def _fmt_amount(self, amount):
        return '{:,.0f}'.format(amount).replace(',', '.')

    def _resolve_config(self):
        self.ensure_one()
        Config = self.env['vas.allocation.config']
        domain = [
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
            ('cost_item_id', '=', self.cost_item_id.id),
            ('scope_type', '=', self.scope_type),
            ('scope_object_id', '=', self.scope_object_id.id
             if self.scope_object_id else False),
            ('sequence', '=', int(self.round_number)),
            ('date_from', '<=', self.date_to),
            '|',
            ('date_to', '=', False),
            ('date_to', '>=', self.date_from),
        ]
        configs = Config.search(domain, order='date_from desc, id desc')
        return configs[:1]

    def _gather_source_lines(self, config):
        """Dòng 154 có khoản mục, chưa đối tượng — hoặc kết quả vòng 1."""
        self.ensure_one()
        if self.money_source == 'prior_round':
            return self._gather_prior_round_as_sources()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('cost_item_id', '=', self.cost_item_id.id),
            ('cost_object_id', '=', False),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('account_id.code', '=like', '154%'),
        ]
        lines = self.env['vas.move.line'].search(domain, order='id')
        net_lines = []
        for line in lines:
            net = line.debit - line.credit
            if not float_is_zero(net, precision_rounding=self.currency_id.rounding):
                net_lines.append((line, net))
        total = sum(n for _l, n in net_lines)
        return net_lines, total

    def _gather_prior_round_as_sources(self):
        """Vòng 2: nguồn = kết quả lượt cha (B2 — đích danh)."""
        self.ensure_one()
        prior = self.parent_run_id
        if not prior:
            raise UserError(_(
                'Vòng 2 thiếu lượt vòng một cha (B2).'
            ))
        if prior.state != 'confirmed':
            raise UserError(_(
                'Lượt cha «%(name)s» không còn hiệu lực.',
                name=prior.display_name,
            ))
        pairs = []
        total = 0.0
        for res in prior.result_ids:
            if float_is_zero(res.amount, precision_rounding=self.currency_id.rounding):
                continue
            pairs.append((res, res.amount))
            total += res.amount
        return pairs, total

    def _candidate_objects(self, config):
        self.ensure_one()
        Object = self.env['vas.cost.object']
        domain = [
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ]
        if self.scope_type == 'process' and self.scope_object_id:
            domain += [
                '|',
                ('id', '=', self.scope_object_id.id),
                ('id', 'child_of', self.scope_object_id.id),
            ]
        elif self.scope_type == 'parent_object' and self.scope_object_id:
            domain += [('parent_id', '=', self.scope_object_id.id)]
        return Object.search(domain)

    def _collect_objects_with_weights(self, config):
        self.ensure_one()
        objs = self._candidate_objects(config)
        criterion = config.criterion if config else 'manual_factor'
        weights = {}
        for obj in objs:
            w = self._criterion_value(obj, criterion, config)
            weights[obj] = w
        return weights

    def _criterion_value(self, obj, criterion, config):
        """Trả tiêu thức; âm sẽ bị chặn sau. 0 = không tham gia."""
        if criterion == 'manual_factor':
            if not config:
                return 0.0
            line = config.factor_ids.filtered(
                lambda f: f.cost_object_id == obj
            )[:1]
            return line.factor if line else 0.0
        if criterion == 'named':
            # Đích danh: hệ số 1 nếu có trong bảng factor, else 0
            if not config:
                return 0.0
            line = config.factor_ids.filtered(
                lambda f: f.cost_object_id == obj
            )[:1]
            return line.factor if line else 0.0
        # Các tiêu thức máy — stub đọc factor nếu có, else 0 (đủ cho lưới số học;
        # nguồn stock/MO gắn đầy đủ ở chặng sau nếu thiếu dữ liệu).
        if not config:
            return 0.0
        line = config.factor_ids.filtered(
            lambda f: f.cost_object_id == obj
        )[:1]
        return line.factor if line else 0.0

    def _assert_sources_alive(self, objects):
        """Yêu cầu 7: kiểm trực tiếp nguồn tại thời điểm chạy — không tin status lưu."""
        orphans = []
        for obj in objects:
            if not obj.source_model or not obj.source_res_id:
                continue
            live = obj._compute_source_status_value()
            if live == 'orphan':
                orphans.append(obj)
        if orphans:
            raise UserError(_(
                'Không chạy phân bổ: đối tượng mồ côi (nguồn không còn tồn tại) — '
                'kiểm trực tiếp tại thời điểm chạy, không dựa trạng thái đã lưu:\n%(list)s',
                list='\n'.join(
                    '- %s — %s (nguồn %s,%s)' % (
                        o.code, o.name, o.source_model, o.source_res_id,
                    ) for o in orphans
                ),
            ))

    def _allocate_by_largest_remainder(self, total, weights, rounding):
        """Chia tiền theo largest remainder; tỷ lệ không làm tròn giữa chừng.

        Trả (shares_dict, exact_ratio_dict). Hoạt động trên |total| rồi trả dấu.
        """
        sign = 1.0 if total >= 0 else -1.0
        abs_total = abs(total)
        denom = sum(weights.values())
        if float_is_zero(denom, precision_digits=10):
            raise UserError(_('Mẫu số bằng 0.'))

        exact_amt = {
            obj: abs_total * (w / denom) for obj, w in weights.items()
        }
        exact_ratio = {
            obj: w / denom for obj, w in weights.items()
        }
        # Đơn vị làm tròn (VND = 1)
        unit = rounding if rounding else 1.0
        floors = {
            obj: math.floor(exact_amt[obj] / unit + 1e-12) * unit
            for obj in weights
        }
        assigned = sum(floors.values())
        # Số đơn vị còn lại cần giao
        remain_units = int(round((abs_total - assigned) / unit))
        order = sorted(
            weights.keys(),
            key=lambda o: (
                -(exact_amt[o] - floors[o]),
                o.code or '',
                o.id,
            ),
        )
        shares_abs = dict(floors)
        for obj in order[:remain_units]:
            shares_abs[obj] = shares_abs[obj] + unit

        shares = {obj: sign * shares_abs[obj] for obj in shares_abs}
        return shares, exact_ratio

    def _write_traces(self, source_pairs, result_map, weights, rounding):
        """Mỗi dòng nguồn chia vào các đối tượng; tổng đóng góp = đúng số dòng."""
        Trace = self.env['vas.allocation.trace']
        for source, net in source_pairs:
            # source là vas.move.line hoặc vas.allocation.result (vòng 2)
            shares, _ratios = self._allocate_by_largest_remainder(
                net, weights, rounding,
            )
            ordered = sorted(shares.keys(), key=lambda o: (o.code or '', o.id))
            for obj in ordered:
                amt = shares[obj]
                if float_is_zero(amt, precision_rounding=rounding):
                    continue
                vals = {
                    'run_id': self.id,
                    'result_id': result_map[obj.id].id,
                    'amount': amt,
                }
                if source._name == 'vas.move.line':
                    vals['source_move_line_id'] = source.id
                else:
                    vals['source_result_id'] = source.id
                Trace.create(vals)

    def _assert_trace_balance(self, source_pairs, rounding, full_allocation=None):
        """Lưới mức dòng nguồn — ĐÚNG đẳng thức (1f / QĐ 51).

        tổng đóng góp (trong lượt này) + phần chưa phân bổ thuộc dòng
        = số tiền nguồn, theo đúng dấu.
        Chỉ khi lượt phân bổ HẾT mới đòi đóng góp == số tiền nguồn.
        """
        Trace = self.env['vas.allocation.trace']
        if full_allocation is None:
            full_allocation = (
                self.compute_ok
                and float_is_zero(
                    self.amount_unallocated, precision_rounding=rounding,
                )
            )
        for source, net in source_pairs:
            if source._name == 'vas.move.line':
                traces = Trace.search([
                    ('run_id', '=', self.id),
                    ('source_move_line_id', '=', source.id),
                ])
            else:
                traces = Trace.search([
                    ('run_id', '=', self.id),
                    ('source_result_id', '=', source.id),
                ])
            contrib = sum(traces.mapped('amount'))
            # Cùng dấu / không vượt |net|
            if not float_is_zero(contrib, precision_rounding=rounding):
                if (
                    float_compare(net, 0.0, precision_rounding=rounding) > 0
                    and float_compare(contrib, 0.0, precision_rounding=rounding) < 0
                ) or (
                    float_compare(net, 0.0, precision_rounding=rounding) < 0
                    and float_compare(contrib, 0.0, precision_rounding=rounding) > 0
                ):
                    raise UserError(_(
                        'Truy vết ngược dấu nguồn %(src)s: góp %(c)s / nguồn %(net)s.',
                        src=source.display_name, c=contrib, net=net,
                    ))
                if float_compare(
                    abs(contrib), abs(net), precision_rounding=rounding,
                ) > 0:
                    raise UserError(_(
                        'Truy vết vượt nguồn %(src)s: góp %(c)s / nguồn %(net)s.',
                        src=source.display_name, c=contrib, net=net,
                    ))
            if full_allocation and float_compare(
                contrib, net, precision_rounding=rounding,
            ) != 0:
                raise UserError(_(
                    'Truy vết lệch (đã phân bổ hết): dòng nguồn %(src)s số %(net)s '
                    'nhưng tổng đóng góp %(c)s (lệch %(d)s).',
                    src=source.display_name,
                    net=net, c=contrib, d=contrib - net,
                ))
            # Phân bổ một phần / mẫu số 0: còn lại = net - contrib (đúng dấu)
            remaining = net - contrib
            if float_compare(
                contrib + remaining, net, precision_rounding=rounding,
            ) != 0:
                raise UserError(_(
                    'Đẳng thức dòng nguồn lệch: góp %(c)s + chưa PB %(u)s ≠ nguồn %(n)s.',
                    c=contrib, u=remaining, n=net,
                ))


class VasAllocationResult(models.Model):
    _name = 'vas.allocation.result'
    _description = 'Kết quả phân bổ theo đối tượng'
    _order = 'sequence, cost_object_id, id'

    run_id = fields.Many2one(
        'vas.allocation.run',
        string='Lượt phân bổ',
        required=True,
        index=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    cost_object_id = fields.Many2one(
        'vas.cost.object',
        string='Đối tượng',
        required=True,
        index=True,
        ondelete='restrict',
    )
    criterion_value = fields.Float(
        string='Giá trị tiêu thức',
        digits=(16, 10),
    )
    ratio = fields.Float(
        string='Tỷ lệ (chưa làm tròn)',
        digits=(16, 10),
        help='Giá trị chưa làm tròn — lưới kiểm 100% dùng cột này. '
             'Hiển thị đủ thập phân.',
    )
    ratio_display = fields.Float(
        string='Tỷ lệ % (hiển thị)',
        compute='_compute_ratio_display',
        digits=(16, 10),
    )
    amount = fields.Monetary(
        string='Số tiền',
        currency_field='currency_id',
        required=True,
    )
    amount_received = fields.Monetary(
        string='Đã được kỳ nhận',
        currency_field='currency_id',
        compute='_compute_amount_received',
        store=True,
    )
    receiving_period_ids = fields.Many2many(
        'vas.costing.period',
        'vas_allocation_result_period_rel',
        'result_id',
        'period_id',
        string='Kỳ đã nhận',
        help='Bước B (nhận trên kỳ) — chặng sau ghi quan hệ này. '
             'Chặng 2 chỉ đọc để chặn ghi đè / liệt kê.',
    )
    currency_id = fields.Many2one(related='run_id.currency_id', store=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    trace_ids = fields.One2many(
        'vas.allocation.trace', 'result_id', string='Truy vết',
    )

    @api.depends('ratio')
    def _compute_ratio_display(self):
        for row in self:
            row.ratio_display = (row.ratio or 0.0) * 100.0

    @api.depends('receiving_period_ids', 'amount')
    def _compute_amount_received(self):
        for row in self:
            row.amount_received = row.amount if row.receiving_period_ids else 0.0

    @api.constrains('receiving_period_ids')
    def _check_one_period_receives(self):
        for row in self:
            if len(row.receiving_period_ids) > 1:
                raise ValidationError(_(
                    'Một phần phân bổ chỉ được một kỳ nhận '
                    '(đối tượng %(obj)s, đang gắn %(n)s kỳ).',
                    obj=row.cost_object_id.display_name,
                    n=len(row.receiving_period_ids),
                ))


class VasAllocationTrace(models.Model):
    _name = 'vas.allocation.trace'
    _description = 'Truy vết phân bổ chi phí (chi tiết số tiền đóng góp)'
    _order = 'id'

    run_id = fields.Many2one(
        'vas.allocation.run',
        string='Lượt phân bổ',
        required=True,
        index=True,
        ondelete='cascade',
    )
    result_id = fields.Many2one(
        'vas.allocation.result',
        string='Kết quả theo đối tượng',
        required=True,
        index=True,
        ondelete='cascade',
    )
    source_move_line_id = fields.Many2one(
        'vas.move.line',
        string='Dòng bút toán nguồn',
        index=True,
        ondelete='restrict',
    )
    source_result_id = fields.Many2one(
        'vas.allocation.result',
        string='Kết quả vòng trước (nguồn)',
        index=True,
        ondelete='restrict',
        help='Vòng 2: nguồn là phần đối tượng cha ở vòng 1.',
    )
    amount = fields.Monetary(
        string='Số tiền đóng góp',
        currency_field='currency_id',
        required=True,
    )
    currency_id = fields.Many2one(related='run_id.currency_id', store=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    cost_object_id = fields.Many2one(
        related='result_id.cost_object_id',
        store=True,
        index=True,
    )

    @api.constrains('source_move_line_id', 'source_result_id')
    def _check_source_present(self):
        for row in self:
            if not row.source_move_line_id and not row.source_result_id:
                raise ValidationError(_(
                    'Bản ghi truy vết phải có dòng bút toán nguồn hoặc kết quả vòng trước.'
                ))
