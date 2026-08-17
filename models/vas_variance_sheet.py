# -*- coding: utf-8 -*-
"""Phiếu xử lý vượt định mức — header + ghi sổ một chiều qua 154."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero

from .vas_variance import TREATMENT_TYPES


class VasVarianceSheet(models.Model):
    _name = 'vas.variance.sheet'
    _description = 'Phiếu xử lý vượt định mức'
    _order = 'id desc'

    name = fields.Char(string='Số phiếu', required=True, copy=False, default='/')
    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        related='company_id.vas_regime_id', store=True, readonly=True,
    )
    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ giá thành',
        required=True, index=True, ondelete='restrict',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('pending_responsibility', 'Chờ xác định trách nhiệm'),
            ('confirmed', 'Đã xác nhận'),
            ('posted', 'Đã ghi sổ'),
            ('reversed', 'Đã đảo'),
        ],
        string='Trạng thái phiếu xử lý',
        default='draft', required=True, index=True, copy=False,
    )
    line_ids = fields.One2many(
        'vas.variance.line', 'sheet_id', string='Dòng vượt / sai hỏng',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, readonly=True,
    )
    amount_total = fields.Monetary(
        string='Tổng xác nhận', currency_field='currency_id',
        compute='_compute_amounts', store=True,
    )
    move_id = fields.Many2one(
        'vas.move', string='Bút toán xử lý', ondelete='restrict', copy=False,
    )
    pullback_move_id = fields.Many2one(
        'vas.move', string='Bút toán kéo về 154', ondelete='restrict', copy=False,
    )
    is_followup = fields.Boolean(string='Phiếu xử lý tiếp', default=False)
    parent_treatment_id = fields.Many2one(
        'vas.variance.treatment', string='Dòng chờ xác minh nguồn',
        ondelete='restrict', index=True, copy=False,
    )
    parent_sheet_id = fields.Many2one(
        related='parent_treatment_id.line_id.sheet_id', store=True,
    )
    reverse_reason = fields.Text(string='Lý do đảo', copy=False)
    note = fields.Text(string='Ghi chú')

    @api.depends('line_ids.amount_confirmed', 'line_ids.line_kind')
    def _compute_amounts(self):
        for sheet in self:
            sheet.amount_total = sum(
                sheet.line_ids.filtered(
                    lambda l: l.line_kind == 'excess',
                ).mapped('amount_confirmed')
            )

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = (
                    Seq.next_by_code('vas.variance.sheet')
                    or _('PV/%s') % fields.Datetime.now().strftime('%Y%m%d%H%M%S')
                )
        return super().create(vals_list)

    def action_open_move(self):
        self.ensure_one()
        move = self.move_id or self.pullback_move_id
        if not move:
            raise UserError(_('Chưa có bút toán.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bút toán phiếu xử lý'),
            'res_model': 'vas.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_set_pending_responsibility(self):
        for sheet in self:
            if sheet.state != 'draft':
                raise UserError(_('Chỉ chuyển từ Nháp.'))
            if not sheet.line_ids.filtered(lambda l: l.line_kind == 'excess'):
                raise UserError(_('Chưa có dòng vượt.'))
            sheet.state = 'pending_responsibility'
        return True

    def action_confirm(self):
        for sheet in self:
            if sheet.state not in ('draft', 'pending_responsibility'):
                raise UserError(_(
                    'Chỉ xác nhận từ Nháp hoặc Chờ xác định trách nhiệm.',
                ))
            if not sheet.line_ids.filtered(lambda l: l.line_kind == 'excess'):
                raise UserError(_(
                    'Không xác nhận phiếu chỉ có dòng tiết kiệm — không có khoản vượt.',
                ))
            sheet._assert_confirmable()
            sheet._lock_and_check_source_ceiling()
            sheet.state = 'confirmed'
        return True

    def action_post(self):
        for sheet in self:
            if sheet.state != 'confirmed':
                raise UserError(_(
                    'Chỉ ghi sổ khi phiếu Đã xác nhận. Hiện: %s.',
                    dict(sheet._fields['state'].selection).get(sheet.state),
                ))
            if sheet.move_id and sheet.move_id.state == 'posted' \
                    and not sheet.move_id.is_reversal:
                raise UserError(_(
                    'B3: phiếu «%s» đã có bút toán còn hiệu lực.',
                    sheet.display_name,
                ))
            period = sheet.period_id
            if period.state in ('posted', 'locked'):
                raise UserError(_(
                    'Kỳ «%(p)s» đã ghi sổ / khóa (%(s)s). '
                    'Đảo bút toán giá thành trước khi ghi sổ phiếu vượt.',
                    p=period.display_name, s=period.state,
                ))
            sheet._lock_and_check_source_ceiling()
            sheet._assert_accounts_and_partners()
            pullback = sheet._create_pullback_move_if_needed()
            move = sheet._create_treatment_move()
            sheet.write({
                'move_id': move.id,
                'pullback_move_id': pullback.id if pullback else False,
                'state': 'posted',
            })
            sheet._update_pending_balances_after_post()
            if period.current_result_id:
                period._invalidate_for_door(
                    'variance',
                    _('Ghi sổ phiếu vượt «%s».', sheet.name),
                )
        return True

    def action_reverse(self, reason=None):
        if reason is None:
            self.ensure_one()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Lý do đảo phiếu xử lý'),
                'res_model': 'vas.costing.reason.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_action_kind': 'variance_reverse',
                    'default_variance_sheet_id': self.id,
                    'default_period_id': self.period_id.id,
                },
            }
        if not (reason or '').strip():
            raise UserError(_('Đảo bắt buộc nhập lý do.'))
        for sheet in self:
            if sheet.state != 'posted':
                raise UserError(_('Chỉ đảo phiếu Đã ghi sổ.'))
            followups = self.search([
                ('parent_treatment_id', 'in', sheet.line_ids.treatment_ids.ids),
                ('state', 'in', (
                    'draft', 'pending_responsibility', 'confirmed', 'posted',
                )),
            ])
            if followups:
                raise UserError(_(
                    'Không đảo «%(s)s»: còn phiếu tiếp «%(f)s».',
                    s=sheet.display_name,
                    f=', '.join(followups.mapped('display_name')),
                ))
            period = sheet.period_id
            if period.state in ('posted', 'locked'):
                raise UserError(_(
                    'Kỳ «%s» đã ghi sổ / khóa — đảo bút toán giá thành trước.',
                    period.display_name,
                ))
            if sheet.move_id and sheet.move_id.state == 'posted':
                sheet.move_id.action_reverse()
            if sheet.pullback_move_id and sheet.pullback_move_id.state == 'posted':
                sheet.pullback_move_id.action_reverse()
            sheet._release_pending_after_reverse()
            sheet.write({
                'state': 'reversed',
                'reverse_reason': reason.strip(),
            })
            if period.current_result_id:
                period._invalidate_for_door(
                    'variance',
                    _('Đảo phiếu vượt «%s».', sheet.name),
                )
        return True

    def action_create_followup(self):
        self.ensure_one()
        pending = self.line_ids.mapped('treatment_ids').filtered(
            lambda t: t.treatment_type == 'pending'
            and t.line_id.sheet_id.state == 'posted'
            and float_compare(
                t.amount_remaining, 0.0,
                precision_rounding=self.currency_id.rounding or 1.0,
            ) > 0
        )
        if not pending:
            raise UserError(_('Không còn dòng chờ xác minh còn hiệu lực.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Phiếu xử lý tiếp'),
            'res_model': 'vas.variance.sheet',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_period_id': self.period_id.id,
                'default_company_id': self.company_id.id,
                'default_is_followup': True,
                'default_parent_treatment_id': pending[0].id,
            },
        }

    def action_suggest_from_bom(self):
        self.ensure_one()
        if 'mrp.bom' not in self.env or 'mrp.production' not in self.env:
            raise UserError(_(
                'Chưa cài module MRP — nút «Lấy số gợi ý» chưa dùng được.\n'
                'Vẫn tạo được phiếu thủ công.',
            ))
        return self.env['vas.variance.bom.helper'].suggest(self)

    def action_warn_stale_pending(self):
        """Cảnh báo khoản chờ xác minh treo quá một kỳ — không chặn."""
        warnings = []
        today = fields.Date.context_today(self)
        for sheet in self.search([('state', '=', 'posted')]):
            for t in sheet.line_ids.mapped('treatment_ids').filtered(
                lambda x: x.treatment_type == 'pending'
                and float_compare(
                    x.amount_remaining, 0.0,
                    precision_rounding=sheet.currency_id.rounding or 1.0,
                ) > 0
            ):
                periods = self.env['vas.costing.period'].search_count([
                    ('company_id', '=', sheet.company_id.id),
                    ('date_from', '>', sheet.period_id.date_to),
                    ('date_from', '<=', today),
                ])
                if periods >= 1:
                    warnings.append(_(
                        'Chờ xác minh %(a)s trên «%(s)s» đã treo %(n)s kỳ.',
                        a=t.amount_remaining, s=sheet.display_name, n=periods,
                    ))
        return warnings

    def _assert_confirmable(self):
        self.ensure_one()
        rounding = self.currency_id.rounding or 1.0
        for line in self.line_ids:
            if line.line_kind == 'saving':
                if line.treatment_ids:
                    raise UserError(_(
                        'Dòng tiết kiệm «%s» không được có phương án xử lý.',
                        line.display_name,
                    ))
                continue
            if not (line.reason or '').strip() and float_compare(
                line.amount_confirmed, line.amount_suggested,
                precision_rounding=rounding,
            ) != 0:
                raise UserError(_(
                    'Dòng «%s»: điều chỉnh số xác nhận bắt buộc có lý do.',
                    line.display_name,
                ))
            if not (line.reason or '').strip() and not line.suggestion_source:
                raise UserError(_(
                    'Dòng «%s» bắt buộc có lý do.', line.display_name,
                ))
            if float_compare(line.amount_confirmed, 0.0, precision_rounding=rounding) < 0:
                raise UserError(_('Số xác nhận không được âm («%s»).', line.display_name))
            if not line.treatment_ids:
                raise UserError(_('Dòng vượt «%s» thiếu phương án.', line.display_name))
            if self.state == 'pending_responsibility' and not (line.cause or '').strip():
                raise UserError(_(
                    'Bắt buộc nguyên nhân trên dòng «%s».', line.display_name,
                ))
            treat_sum = sum(line.treatment_ids.mapped('amount'))
            if float_compare(treat_sum, line.amount_confirmed, precision_rounding=rounding) != 0:
                raise UserError(_(
                    'Tổng phương án (%(t)s) lệch số xác nhận (%(c)s) dòng «%(l)s». '
                    'Lệch %(d)s.',
                    t=treat_sum, c=line.amount_confirmed, l=line.display_name,
                    d=treat_sum - line.amount_confirmed,
                ))
            for t in line.treatment_ids:
                t._assert_partner_employee_reason()

    def _lock_and_check_source_ceiling(self):
        self.ensure_one()
        rounding = self.currency_id.rounding or 1.0
        cr = self.env.cr
        if self.is_followup and self.parent_treatment_id:
            cr.execute(
                'SELECT id FROM vas_variance_treatment WHERE id = %s FOR UPDATE',
                [self.parent_treatment_id.id],
            )
            parent = self.parent_treatment_id
            parent.invalidate_recordset()
            take = sum(
                self.line_ids.filtered(lambda l: l.line_kind == 'excess')
                .mapped('amount_confirmed')
            )
            if parent.treatment_type != 'pending':
                raise UserError(_('Chỉ dòng chờ xác minh mới làm nguồn phiếu tiếp.'))
            if parent.line_id.sheet_id.state != 'posted':
                raise UserError(_('Dòng chờ nguồn phải thuộc phiếu đã ghi sổ.'))
            others = self.search([
                ('parent_treatment_id', '=', parent.id),
                ('id', '!=', self.id),
                ('state', 'in', ('confirmed', 'posted')),
            ])
            available = parent.amount_remaining
            # Các phiếu confirmed chưa post chưa trừ vào amount_remaining
            confirmed_unposted = others.filtered(lambda s: s.state == 'confirmed')
            reserved = sum(
                confirmed_unposted.mapped(
                    lambda s: sum(
                        s.line_ids.filtered(lambda l: l.line_kind == 'excess')
                        .mapped('amount_confirmed')
                    )
                )
            )
            if float_compare(
                take + reserved, available, precision_rounding=rounding,
            ) > 0:
                raise UserError(_(
                    'Phiếu tiếp lấy %(t)s vượt còn chờ %(r)s (đã giữ chỗ %(k)s).',
                    t=take, r=available, k=reserved,
                ))
            return
        sources = {}
        for line in self.line_ids.filtered(lambda l: l.line_kind == 'excess'):
            if line.source_model and line.source_res_id:
                key = (line.source_model, line.source_res_id)
                sources[key] = sources.get(key, 0.0) + line.amount_confirmed
        move_ids = sorted(rid for (m, rid) in sources if m == 'stock.move')
        vml_ids = sorted(rid for (m, rid) in sources if m == 'vas.move.line')
        if move_ids:
            cr.execute(
                'SELECT id FROM stock_move WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
                [move_ids],
            )
        if vml_ids:
            cr.execute(
                'SELECT id FROM vas_move_line WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
                [vml_ids],
            )
        for (model, res_id), ask in sources.items():
            used = self._source_amount_used(model, res_id, exclude_sheet=self)
            available = self._source_amount_available(model, res_id)
            if float_compare(used + ask, available, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Trần nguồn %(model)s#%(id)s: đã dùng %(u)s + %(a)s > khả dụng %(v)s.',
                    model=model, id=res_id, u=used, a=ask, v=available,
                ))

    def _source_amount_available(self, model, res_id):
        Sync = self.env['vas.sync']
        if model == 'stock.move':
            move = self.env['stock.move'].browse(res_id).exists()
            return abs(Sync._cogs_amount(move) or 0.0) if move else 0.0
        if model == 'vas.move.line':
            line = self.env['vas.move.line'].browse(res_id).exists()
            return abs(line.debit - line.credit) if line else 0.0
        return 0.0

    def _source_amount_used(self, model, res_id, exclude_sheet=None):
        domain = [
            ('source_model', '=', model),
            ('source_res_id', '=', res_id),
            ('line_kind', '=', 'excess'),
            ('sheet_id.state', 'in', ('confirmed', 'posted')),
        ]
        if exclude_sheet:
            domain.append(('sheet_id', '!=', exclude_sheet.id))
        return sum(self.env['vas.variance.line'].search(domain).mapped('amount_confirmed'))

    def _assert_accounts_and_partners(self):
        self.ensure_one()
        cfg = self.env['vas.variance.account.config']._get_for(
            self.company_id, self.regime_id,
        )
        if not cfg:
            raise UserError(_(
                'Chưa cấu hình TK xử lý vượt cho «%(c)s» / «%(r)s».',
                c=self.company_id.display_name, r=self.regime_id.display_name,
            ))
        for line in self.line_ids.filtered(lambda l: l.line_kind == 'excess'):
            for t in line.treatment_ids:
                acc = t.account_id or cfg._account_for_type(t.treatment_type)
                if not acc:
                    raise UserError(_(
                        'Thiếu TK cấu hình phương án «%(t)s» dòng «%(l)s».',
                        t=dict(TREATMENT_TYPES).get(t.treatment_type),
                        l=line.display_name,
                    ))
                self._assert_account_usable(acc)
                t.account_id = acc.id
                t._assert_partner_employee_reason()

    def _assert_account_usable(self, account):
        if account.regime_id != self.regime_id:
            raise UserError(_(
                'TK «%(a)s» sai chế độ — kỳ dùng «%(r)s».',
                a=account.display_name, r=self.regime_id.display_name,
            ))
        if not account.active:
            raise UserError(_('TK «%s» không hoạt động.', account.display_name))
        if self.env['vas.account'].search_count([('parent_id', '=', account.id)]):
            raise UserError(_(
                'TK «%s» là tổng hợp — chỉ dùng tài khoản lá.',
                account.display_name,
            ))

    def _general_journal(self):
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ tổng hợp VAS.'))
        return journal

    def _wip_account(self, cost_object):
        if not cost_object or not cost_object.wip_account_id:
            raise UserError(_('Thiếu TK dở dang (154) trên đối tượng.'))
        return cost_object.wip_account_id

    def _create_pullback_move_if_needed(self):
        self.ensure_one()
        if self.is_followup:
            return self.env['vas.move']
        period = self.period_id
        if period.posting_mode != 'immediate':
            return self.env['vas.move']
        lots = period.provisional_lot_ids.filtered(
            lambda l: l.state == 'posted'
            and l.move_id and l.move_id.state == 'posted'
            and not l.move_id.is_reversal
        )
        if not lots:
            return self.env['vas.move']
        rounding = self.currency_id.rounding or 1.0
        excess = sum(
            self.line_ids.filtered(lambda l: l.line_kind == 'excess')
            .mapped('amount_confirmed')
        )
        if float_is_zero(excess, precision_rounding=rounding):
            return self.env['vas.move']
        cutoff = fields.Datetime.to_datetime('%s 23:59:59' % period.date_to)
        sold_map = period._assign_sold_remaining_fifo(lots, cutoff)
        qty_all = sum(lots.mapped('qty')) or 1.0
        qty_sold = sum(sold_map[l.id][1] for l in lots)
        qty_rem = qty_all - qty_sold
        stock_amt, cogs_amt = period._split_lot_diff_stock_cogs(
            excess, qty_rem, qty_sold, rounding,
        )
        sample = lots[0]
        stock_acc = period._require_product_vas_account(
            sample.product_id, 'product_inventory',
        )
        cogs_acc = period._require_product_vas_account(
            sample.product_id, 'product_cogs',
        )
        obj = self.line_ids[:1].cost_object_id or sample.cost_object_id
        wip = self._wip_account(obj)
        lines = []

        def _pair(dest, amount, label):
            if float_is_zero(amount, precision_rounding=rounding):
                return
            lines.append((0, 0, {
                'account_id': wip.id, 'name': label,
                'debit': amount, 'credit': 0.0,
                'currency_id': self.currency_id.id,
            }))
            lines.append((0, 0, {
                'account_id': dest.id, 'name': label,
                'debit': 0.0, 'credit': amount,
                'currency_id': self.currency_id.id,
            }))

        _pair(stock_acc, stock_amt, _('Kéo vượt về 154 (tồn) %s', self.name))
        _pair(cogs_acc, cogs_amt, _('Kéo vượt về 154 (đã bán) %s', self.name))
        if not lines:
            return self.env['vas.move']
        move = self.env['vas.move'].create({
            'date': period.date_to,
            'journal_id': self._general_journal().id,
            'regime_id': self.regime_id.id,
            'move_kind': 'manual',
            'ref': _('Kéo vượt %s', self.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'source_model': 'vas.variance.sheet',
            'source_res_id': 0,
            'source_ref': 'variance_pullback',
            'line_ids': lines,
        })
        move.action_post()
        return move

    def _create_treatment_move(self):
        self.ensure_one()
        journal = self._general_journal()
        rounding = self.currency_id.rounding or 1.0
        cmds = []
        if self.is_followup and self.parent_treatment_id:
            pending_acc = (
                self.parent_treatment_id.account_used_id
                or self.parent_treatment_id.account_id
            )
            for line in self.line_ids.filtered(lambda l: l.line_kind == 'excess'):
                for t in line.treatment_ids:
                    if float_is_zero(t.amount, precision_rounding=rounding):
                        continue
                    cmds.append((0, 0, {
                        'account_id': t.account_id.id,
                        'name': _('Xử lý tiếp %s', self.name),
                        'debit': t.amount, 'credit': 0.0,
                        'currency_id': self.currency_id.id,
                        'partner_id': t.partner_id.id if t.partner_id else False,
                    }))
                    cmds.append((0, 0, {
                        'account_id': pending_acc.id,
                        'name': _('Giảm chờ %s', self.name),
                        'debit': 0.0, 'credit': t.amount,
                        'currency_id': self.currency_id.id,
                    }))
                    t.account_used_id = t.account_id.id
        else:
            for line in self.line_ids.filtered(lambda l: l.line_kind == 'excess'):
                wip = self._wip_account(line.cost_object_id)
                for t in line.treatment_ids:
                    if float_is_zero(t.amount, precision_rounding=rounding):
                        continue
                    cmds.append((0, 0, {
                        'account_id': t.account_id.id,
                        'name': _('Xử lý vượt %s', line.display_name),
                        'debit': t.amount if t.amount > 0 else 0.0,
                        'credit': -t.amount if t.amount < 0 else 0.0,
                        'currency_id': self.currency_id.id,
                        'partner_id': t.partner_id.id if t.partner_id else False,
                        'cost_object_id': line.cost_object_id.id,
                        'cost_item_id': line.cost_item_id.id if line.cost_item_id else False,
                    }))
                    cmds.append((0, 0, {
                        'account_id': wip.id,
                        'name': _('Kết chuyển vượt %s', line.display_name),
                        'debit': -t.amount if t.amount < 0 else 0.0,
                        'credit': t.amount if t.amount > 0 else 0.0,
                        'currency_id': self.currency_id.id,
                        'cost_object_id': line.cost_object_id.id,
                        'cost_item_id': line.cost_item_id.id if line.cost_item_id else False,
                    }))
                    t.account_used_id = t.account_id.id
        if not cmds:
            raise UserError(_('Không có số tiền xử lý để ghi sổ.'))
        move = self.env['vas.move'].create({
            'date': self.period_id.date_to,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'manual',
            'ref': _('Xử lý vượt %s', self.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'source_model': 'vas.variance.sheet',
            'source_res_id': self.id,
            'source_ref': 'variance_treatment',
            'line_ids': cmds,
        })
        move.action_post()
        return move

    def _update_pending_balances_after_post(self):
        self.ensure_one()
        for t in self.line_ids.mapped('treatment_ids'):
            if t.treatment_type == 'pending':
                t.amount_remaining = t.amount
                t.amount_processed = 0.0
        if self.is_followup and self.parent_treatment_id:
            take = sum(
                self.line_ids.filtered(lambda l: l.line_kind == 'excess')
                .mapped('amount_confirmed')
            )
            parent = self.parent_treatment_id
            parent.amount_processed = parent.amount_processed + take
            parent.amount_remaining = parent.amount - parent.amount_processed

    def _release_pending_after_reverse(self):
        self.ensure_one()
        if self.is_followup and self.parent_treatment_id:
            take = sum(
                self.line_ids.filtered(lambda l: l.line_kind == 'excess')
                .mapped('amount_confirmed')
            )
            parent = self.parent_treatment_id
            parent.amount_processed = parent.amount_processed - take
            parent.amount_remaining = parent.amount - parent.amount_processed
