# -*- coding: utf-8 -*-
"""W12 Chặng 3 — dở dang đầu/cuối kỳ, phiên bản kết quả, duyệt, dấu vân tay."""
import hashlib
import json
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


GROUP_A_TYPES = ('product', 'operation', 'process', 'workshop')
GROUP_B_TYPES = ('project', 'sale_order', 'contract')


class VasAllocationReceiveLog(models.Model):
    _name = 'vas.allocation.receive.log'
    _description = 'Nhật ký nhận / hoàn tác nhận phân bổ'
    _order = 'create_date desc, id desc'

    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ', required=True,
        index=True, ondelete='restrict',
    )
    result_id = fields.Many2one(
        'vas.allocation.result', string='Phần phân bổ',
        index=True, ondelete='restrict',
    )
    action = fields.Selection(
        [('receive', 'Nhận'), ('unreceive', 'Hoàn tác nhận')],
        string='Hành động', required=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Người thao tác', required=True,
        default=lambda self: self.env.user, ondelete='restrict',
    )
    reason = fields.Text(string='Lý do')
    company_id = fields.Many2one(
        related='period_id.company_id', store=True,
    )


class VasOpeningWip(models.Model):
    _name = 'vas.opening.wip'
    _description = 'Dở dang đầu kỳ (bảng khai)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Tên', required=True, default='Dở dang đầu kỳ')
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True,
        default=lambda self: self.env.company, ondelete='restrict',
    )
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    date = fields.Date(
        string='Ngày số dư', required=True,
        help='Ngày tham chiếu số dư Nợ 154 để lưới kiểm bốn nhóm.',
    )
    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ gắn (tuỳ chọn)',
        ondelete='restrict',
    )
    detail_by_item = fields.Boolean(
        string='Nhập chi tiết theo khoản mục', default=False,
    )
    detail_level = fields.Selection(
        [
            ('total', 'Một cột tổng theo đối tượng'),
            ('root3', 'Tách ba khoản mục gốc'),
            ('full', 'Theo toàn bộ cây khoản mục'),
        ],
        string='Mức chi tiết', default='total', required=True,
    )
    line_ids = fields.One2many(
        'vas.opening.wip.line', 'sheet_id', string='Dòng',
    )
    group_b_manual_amount = fields.Monetary(
        string='Nhóm 2 (khai tay — nhóm B)',
        currency_field='currency_id', default=0.0,
        help='Engine nhóm B chưa nối — khai tay.',
    )
    amount_group1 = fields.Monetary(
        string='Nhóm 1', currency_field='currency_id', readonly=True,
    )
    amount_group2 = fields.Monetary(
        string='Nhóm 2', currency_field='currency_id', readonly=True,
    )
    amount_group3 = fields.Monetary(
        string='Nhóm 3', currency_field='currency_id', readonly=True,
    )
    amount_group4 = fields.Monetary(
        string='Nhóm 4', currency_field='currency_id', readonly=True,
    )
    amount_balance_154 = fields.Monetary(
        string='Số dư Nợ 154', currency_field='currency_id', readonly=True,
    )
    amount_diff = fields.Monetary(
        string='Chênh lệch', currency_field='currency_id', readonly=True,
    )
    locked = fields.Boolean(string='Đã khóa số dư đầu kỳ', default=False)
    state = fields.Selection(
        [('draft', 'Nháp'), ('checked', 'Đã kiểm'), ('locked', 'Đã khóa')],
        default='draft', string='Trạng thái',
    )

    def action_clear_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        return True

    def action_export_csv(self):
        self.ensure_one()
        import base64
        import io
        buf = io.StringIO()
        buf.write('object_code,cost_item_code,amount\n')
        for line in self.line_ids:
            buf.write('%s,%s,%s\n' % (
                line.cost_object_id.code or '',
                line.cost_item_id.code or '',
                line.amount,
            ))
        att = self.env['ir.attachment'].create({
            'name': 'do_dang_dau_ky_%s.csv' % self.id,
            'type': 'binary',
            'datas': base64.b64encode(buf.getvalue().encode('utf-8')),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % att.id,
            'target': 'self',
        }

    def action_import_csv(self, data_text):
        """Nhập CSV object_code,cost_item_code,amount — dùng trong test/wizard."""
        self.ensure_one()
        Object = self.env['vas.cost.object']
        Item = self.env['vas.cost.item']
        lines = []
        for i, raw in enumerate(data_text.strip().splitlines()):
            if i == 0 and 'object_code' in raw:
                continue
            parts = [p.strip() for p in raw.split(',')]
            if len(parts) < 3:
                continue
            obj = Object.search([
                ('code', '=', parts[0]),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not obj:
                raise UserError(_('Không tìm thấy đối tượng mã %(c)s', c=parts[0]))
            item = False
            if parts[1]:
                item = Item.search([
                    ('code', '=', parts[1]),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
            lines.append({
                'sheet_id': self.id,
                'cost_object_id': obj.id,
                'cost_item_id': item.id if item else False,
                'amount': float(parts[2]),
            })
        self.env['vas.opening.wip.line'].create(lines)
        return len(lines)

    def action_copy_from_prior_period(self):
        self.ensure_one()
        prior = self.search([
            ('company_id', '=', self.company_id.id),
            ('date', '<', self.date),
            ('id', '!=', self.id),
        ], order='date desc, id desc', limit=1)
        if not prior:
            raise UserError(_('Không có bảng dở dang đầu kỳ trước để lấy số.'))
        vals = []
        for line in prior.line_ids:
            vals.append({
                'sheet_id': self.id,
                'cost_object_id': line.cost_object_id.id,
                'cost_item_id': line.cost_item_id.id if line.cost_item_id else False,
                'wip_account_id': line.wip_account_id.id,
                'amount': line.amount,
            })
        self.env['vas.opening.wip.line'].create(vals)
        return True

    def _balance_154(self):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('account_id.code', '=like', '154%'),
            ('date', '<=', self.date),
        ])
        return sum(l.debit - l.credit for l in lines)

    def _compute_four_groups(self):
        """Tính bốn nhóm loại trừ nhau."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 1.0
        # Nhóm 1: trực tiếp gắn đối tượng nhóm A (có cost_object, có trên 154)
        direct = self.env['vas.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('account_id.code', '=like', '154%'),
            ('cost_object_id', '!=', False),
            ('cost_object_id.object_type', 'in', list(GROUP_A_TYPES)),
            ('date', '<=', self.date),
        ])
        g1 = sum(l.debit - l.credit for l in direct)
        # Nhóm 4: phân bổ còn hiệu lực, đối tượng A, chưa kỳ nhận
        Result = self.env['vas.allocation.result']
        results = Result.search([
            ('company_id', '=', self.company_id.id),
            ('cost_object_id.object_type', 'in', list(GROUP_A_TYPES)),
        ])
        g4 = 0.0
        for res in results:
            if res.receiving_period_ids:
                continue
            if not res.run_id._run_occupies_ceiling():
                continue
            g4 += res.amount
        # Nhóm 3: chưa phân bổ được trên lượt còn hiệu lực
        runs = self.env['vas.allocation.run'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'confirmed'),
        ])
        g3 = sum(runs.mapped('amount_unallocated'))
        # Nhóm 2: khai tay
        g2 = self.group_b_manual_amount
        bal = self._balance_154()
        diff = (g1 + g2 + g3 + g4) - bal
        self.write({
            'amount_group1': g1,
            'amount_group2': g2,
            'amount_group3': g3,
            'amount_group4': g4,
            'amount_balance_154': bal,
            'amount_diff': diff,
        })
        return g1, g2, g3, g4, bal, diff

    def action_check_four_groups(self):
        for sheet in self:
            sheet._assert_detail_level_lines()
            g1, g2, g3, g4, bal, diff = sheet._compute_four_groups()
            rounding = sheet.currency_id.rounding or 1.0
            if not float_is_zero(diff, precision_rounding=rounding):
                raise UserError(_(
                    'Lưới bốn nhóm lệch số dư Nợ 154.\n'
                    'Nhóm 1=%(g1)s · Nhóm 2=%(g2)s · Nhóm 3=%(g3)s · Nhóm 4=%(g4)s\n'
                    'Tổng nhóm=%(sum)s · Số dư 154=%(bal)s · Lệch=%(diff)s.\n'
                    'Không khóa được số dư đầu kỳ.',
                    g1=g1, g2=g2, g3=g3, g4=g4,
                    sum=g1 + g2 + g3 + g4, bal=bal, diff=diff,
                ))
            sheet.state = 'checked'
        return True

    def _root3_cost_items(self):
        """Ba khoản mục gốc hệ thống NVLTT / NCTT / CPC."""
        Item = self.env['vas.cost.item']
        items = Item.browse()
        for code in ('NVLTT', 'NCTT', 'CPC'):
            found = Item.search([
                ('code', '=', code),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if found:
                items |= found
        return items

    def _assert_detail_level_lines(self):
        """Ba mức chi tiết: kiểm cấu trúc dòng khớp mức đã chọn."""
        self.ensure_one()
        if not self.line_ids:
            return
        if self.detail_level == 'total':
            bad = self.line_ids.filtered('cost_item_id')
            if bad:
                raise UserError(_(
                    'Mức «Một cột tổng theo đối tượng»: dòng không được gắn khoản mục. '
                    'Dòng lỗi: %(l)s',
                    l=', '.join(bad.mapped('cost_object_id.code')),
                ))
            # Mỗi đối tượng tối đa một dòng
            codes = self.line_ids.mapped('cost_object_id.id')
            if len(codes) != len(set(codes)):
                raise UserError(_(
                    'Mức tổng: mỗi đối tượng chỉ một dòng số tổng.'
                ))
        elif self.detail_level == 'root3':
            roots = self._root3_cost_items()
            if len(roots) < 3:
                raise UserError(_(
                    'Mức «Tách ba khoản mục gốc» cần đủ NVLTT/NCTT/CPC trên công ty.'
                ))
            bad = self.line_ids.filtered(
                lambda l: not l.cost_item_id or l.cost_item_id not in roots
            )
            if bad:
                raise UserError(_(
                    'Mức root3: mọi dòng phải gắn đúng một trong NVLTT/NCTT/CPC. '
                    'Dòng lỗi: %(l)s',
                    l=', '.join(
                        '%s/%s' % (
                            x.cost_object_id.code,
                            x.cost_item_id.code if x.cost_item_id else '?',
                        ) for x in bad
                    ),
                ))
        else:  # full
            missing = self.line_ids.filtered(lambda l: not l.cost_item_id)
            if missing:
                raise UserError(_(
                    'Mức «Theo toàn bộ cây khoản mục»: mọi dòng phải có khoản mục. '
                    'Thiếu trên đối tượng: %(l)s',
                    l=', '.join(missing.mapped('cost_object_id.code')),
                ))
            # Không cho nút tổng hợp
            agg = self.line_ids.filtered(
                lambda l: l.cost_item_id and l.cost_item_id.is_aggregate_node
            )
            if agg:
                raise UserError(_(
                    'Mức full: chỉ dùng khoản mục lá, không dùng nút tổng hợp (%(c)s).',
                    c=', '.join(agg.mapped('cost_item_id.code')),
                ))

    def action_validate_detail_level(self):
        for sheet in self:
            sheet._assert_detail_level_lines()
        return True

    def amount_total_by_object(self):
        """Tổng theo đối tượng — dùng ca kiểm ba mức cộng đúng."""
        self.ensure_one()
        totals = {}
        for line in self.line_ids:
            totals.setdefault(line.cost_object_id, 0.0)
            totals[line.cost_object_id] += line.amount
        return totals

    def action_lock(self):
        self.action_check_four_groups()
        self.write({'locked': True, 'state': 'locked'})
        return True


class VasOpeningWipLine(models.Model):
    _name = 'vas.opening.wip.line'
    _description = 'Dòng dở dang đầu kỳ'
    _order = 'id'

    sheet_id = fields.Many2one(
        'vas.opening.wip', required=True, index=True, ondelete='cascade',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', string='Đối tượng', required=True,
        ondelete='restrict',
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item', string='Khoản mục', ondelete='restrict',
    )
    wip_account_id = fields.Many2one(
        'vas.account', string='Tài khoản dở dang',
        ondelete='restrict',
    )
    amount = fields.Monetary(string='Số tiền', currency_field='currency_id')
    currency_id = fields.Many2one(related='sheet_id.currency_id')
    company_id = fields.Many2one(related='sheet_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        Acc = self.env['vas.account']
        for vals in vals_list:
            if not vals.get('wip_account_id') and vals.get('sheet_id'):
                sheet = self.env['vas.opening.wip'].browse(vals['sheet_id'])
                acc = Acc.search([
                    ('code', '=', '154'),
                    ('regime_id', '=', sheet.company_id.vas_regime_id.id),
                ], limit=1)
                if acc:
                    vals['wip_account_id'] = acc.id
        return super().create(vals_list)


class VasClosingWip(models.Model):
    _name = 'vas.closing.wip'
    _description = 'Bản dở dang cuối kỳ / ngày báo cáo'
    _order = 'id desc'

    name = fields.Char(string='Tên', required=True, default='Dở dang cuối kỳ')
    kind = fields.Selection(
        [('period_end', 'Cuối kỳ tính giá thành'),
         ('report_date', 'Ngày báo cáo bất kỳ')],
        string='Loại', required=True, default='period_end',
    )
    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ', ondelete='restrict', index=True,
    )
    report_date = fields.Date(string='Ngày báo cáo')
    confirm_version = fields.Integer(string='Phiên bản xác nhận', default=1)
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company, ondelete='restrict',
    )
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('suggested', 'Đã tạo gợi ý'),
            ('pending_confirm', 'Chờ xác nhận'),
            ('confirmed', 'Đã xác nhận'),
            ('needs_review', 'Cần kiểm tra lại'),
        ],
        string='Trạng thái bản dở dang',
        default='draft', required=True, index=True,
        help='Trạng thái của BẢN dở dang — khác sáu trạng thái của kỳ.',
    )
    line_ids = fields.One2many('vas.closing.wip.line', 'sheet_id', string='Dòng')
    delta_after_regen = fields.Monetary(
        string='Chênh lệch gợi ý mới', currency_field='currency_id',
        help='Hiện khi tạo lại gợi ý trên bản đã xác nhận — không ghi đè số xác nhận.',
    )
    reopen_reason = fields.Text(string='Lý do mở lại')
    note = fields.Text(string='Ghi chú')

    @api.constrains('kind', 'period_id', 'report_date')
    def _check_kind_anchor(self):
        for rec in self:
            if rec.kind == 'period_end' and not rec.period_id:
                raise ValidationError(_('Ca A bắt buộc gắn kỳ tính giá thành.'))
            if rec.kind == 'report_date' and not rec.report_date:
                raise ValidationError(_('Ca B bắt buộc có ngày báo cáo.'))

    def action_regen_suggestion(self):
        """Tạo / tạo lại số gợi ý. Bản đã xác nhận: hiện chênh, không ghi đè xác nhận."""
        for sheet in self:
            suggested_map = sheet._build_suggestions()
            if sheet.state == 'confirmed':
                old_total = sum(sheet.line_ids.mapped('amount_confirmed'))
                new_total = sum(suggested_map.values())
                # Không ghi đè số xác nhận / gợi ý đã khóa — chỉ hiện chênh
                sheet.delta_after_regen = new_total - old_total
                sheet.state = 'needs_review'
            else:
                sheet.line_ids.unlink()
                Line = self.env['vas.closing.wip.line']
                for (obj_id, item_id), amt in suggested_map.items():
                    Line.create({
                        'sheet_id': sheet.id,
                        'cost_object_id': obj_id,
                        'cost_item_id': item_id or False,
                        'amount_suggested': amt,
                        'amount_adjustment': 0.0,
                    })
                sheet.state = 'pending_confirm'
                sheet.delta_after_regen = 0.0
        return True

    def _build_suggestions(self):
        """Gợi ý đơn giản: theo đối tượng kỳ, bằng chi phí trực tiếp + chung đã nhận."""
        self.ensure_one()
        result = {}
        period = self.period_id
        if not period:
            return result
        for obj in period.cost_object_ids:
            direct = period._amount_direct_for_object(obj)
            overhead = period._amount_received_overhead_for_object(obj)
            result[(obj.id, 0)] = direct + overhead
        return result

    def action_confirm(self):
        for sheet in self:
            if sheet.state not in ('pending_confirm', 'suggested', 'needs_review', 'draft'):
                if sheet.state == 'confirmed':
                    continue
            for line in sheet.line_ids:
                if (
                    not float_is_zero(
                        line.amount_adjustment,
                        precision_rounding=sheet.currency_id.rounding,
                    )
                    and not line.reason_adjustment
                ):
                    raise UserError(_(
                        'Lý do điều chỉnh bắt buộc khi số điều chỉnh khác 0 '
                        '(đối tượng %(o)s).',
                        o=line.cost_object_id.display_name,
                    ))
                line.write({
                    'amount_confirmed': (
                        (line.amount_suggested or 0.0)
                        + (line.amount_adjustment or 0.0)
                    ),
                    'confirmer_id': self.env.user.id,
                    'confirm_date': fields.Datetime.now(),
                })
            sheet.state = 'confirmed'
            if sheet.period_id and sheet.period_id.state not in ('draft',):
                # Cửa 2: đổi dở dang cuối → hết hiệu lực kết quả
                sheet.period_id._invalidate_for_door(
                    'closing_wip',
                    _('Cửa 2 — bản dở dang cuối kỳ xác nhận lại: %(n)s', n=sheet.name),
                )
        return True

    def action_reopen(self):
        for sheet in self:
            if sheet.period_id and sheet.period_id.state == 'locked':
                raise UserError(_('Kỳ đã khóa — không mở lại bản dở dang.'))
            if not sheet.reopen_reason:
                raise UserError(_('Mở lại bắt buộc nhập lý do.'))
            if sheet.period_id and sheet.state == 'confirmed':
                sheet.period_id._invalidate_for_door(
                    'closing_wip',
                    _('Cửa 2 — mở lại bản dở dang: %(r)s', r=sheet.reopen_reason),
                )
            sheet.state = 'draft'
        return True

    def action_view_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lịch sử bản dở dang'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'domain': [
                '|',
                ('period_id', '=', self.period_id.id if self.period_id else 0),
                ('report_date', '=', self.report_date),
                ('company_id', '=', self.company_id.id),
            ],
        }

    def total_confirmed(self):
        self.ensure_one()
        return sum(self.line_ids.mapped('amount_confirmed'))


class VasClosingWipLine(models.Model):
    _name = 'vas.closing.wip.line'
    _description = 'Dòng dở dang cuối kỳ'
    _order = 'id'

    sheet_id = fields.Many2one(
        'vas.closing.wip', required=True, ondelete='cascade', index=True,
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', string='Đối tượng', required=True, ondelete='restrict',
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item', string='Khoản mục', ondelete='restrict',
    )
    amount_suggested = fields.Monetary(
        string='Số hệ thống gợi ý', currency_field='currency_id', readonly=True,
    )
    amount_adjustment = fields.Monetary(
        string='Số điều chỉnh', currency_field='currency_id', default=0.0,
    )
    amount_confirmed = fields.Monetary(
        string='Số xác nhận', currency_field='currency_id',
        help='Số xác nhận = gợi ý + điều chỉnh. Khóa sau khi xác nhận bản.',
    )
    reason_adjustment = fields.Text(string='Lý do điều chỉnh')
    confirmer_id = fields.Many2one('res.users', string='Người xác nhận', ondelete='restrict')
    confirm_date = fields.Datetime(string='Thời điểm xác nhận')
    currency_id = fields.Many2one(related='sheet_id.currency_id')
    company_id = fields.Many2one(related='sheet_id.company_id', store=True)

    @api.onchange('amount_suggested', 'amount_adjustment')
    def _onchange_confirmed_formula(self):
        for line in self:
            if line.sheet_id.state == 'confirmed':
                continue
            line.amount_confirmed = (
                (line.amount_suggested or 0.0) + (line.amount_adjustment or 0.0)
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'amount_confirmed' not in vals:
                vals['amount_confirmed'] = (
                    vals.get('amount_suggested', 0.0) or 0.0
                ) + (vals.get('amount_adjustment', 0.0) or 0.0)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('amount_suggested', 'amount_adjustment')):
            for line in self:
                if line.sheet_id.state == 'confirmed':
                    continue
                confirmed = (
                    (line.amount_suggested or 0.0) + (line.amount_adjustment or 0.0)
                )
                if float_compare(
                    confirmed, line.amount_confirmed,
                    precision_rounding=line.currency_id.rounding or 1.0,
                ) != 0:
                    super(VasClosingWipLine, line).write({
                        'amount_confirmed': confirmed,
                    })
        return res

    @api.constrains('amount_adjustment', 'reason_adjustment')
    def _check_reason(self):
        for line in self:
            rounding = line.currency_id.rounding or 1.0
            if (
                not float_is_zero(line.amount_adjustment, precision_rounding=rounding)
                and not line.reason_adjustment
            ):
                raise ValidationError(_(
                    'Lý do điều chỉnh bắt buộc khi số điều chỉnh khác 0.'
                ))


class VasCostingResultVersion(models.Model):
    _name = 'vas.costing.result.version'
    _description = 'Phiên bản kết quả tính giá thành'
    _order = 'period_id, version desc, id desc'

    name = fields.Char(string='Tên', compute='_compute_name', store=True)
    period_id = fields.Many2one(
        'vas.costing.period', required=True, index=True, ondelete='restrict',
    )
    version = fields.Integer(string='Phiên bản', default=1)
    effectiveness = fields.Selection(
        [('effective', 'Còn hiệu lực'), ('ineffective', 'Hết hiệu lực')],
        string='Hiệu lực', default='effective', required=True, index=True,
    )
    invalidation_reason = fields.Text(string='Lý do hết hiệu lực')
    invalidation_door = fields.Selection(
        [
            ('allocation', 'Cửa 1 — phần phân bổ kỳ nhận'),
            ('closing_wip', 'Cửa 2 — dở dang cuối kỳ'),
            ('objects', 'Cửa 3 — danh sách đối tượng'),
            ('odoo_source', 'Cửa 4 — dữ liệu nguồn bên Odoo'),
            ('variance', 'Cửa 5 — phiếu xử lý vượt định mức'),
        ],
        string='Cửa hết hiệu lực',
    )
    fingerprint = fields.Char(string='Dấu vân tay', index=True)
    fingerprint_payload = fields.Text(string='Payload dấu vân tay')
    opening_wip = fields.Monetary(currency_field='currency_id')
    amount_direct = fields.Monetary(string='Chi phí trực tiếp', currency_field='currency_id')
    amount_overhead = fields.Monetary(
        string='Chi phí chung đã nhận', currency_field='currency_id',
    )
    amount_reduction = fields.Monetary(
        string='Khoản giảm giá thành', currency_field='currency_id',
    )
    closing_wip = fields.Monetary(currency_field='currency_id')
    total_cost = fields.Monetary(string='Tổng giá thành', currency_field='currency_id')
    line_ids = fields.One2many(
        'vas.costing.result.line', 'version_id', string='Chi tiết theo đối tượng',
    )
    move_id = fields.Many2one(
        'vas.move', string='Bút toán 154→155', ondelete='restrict', copy=False,
        help='B3: tối đa một bút toán còn hiệu lực cho phiên bản.',
    )
    currency_id = fields.Many2one(related='period_id.currency_id', store=True)
    company_id = fields.Many2one(related='period_id.company_id', store=True)
    approval_ids = fields.One2many(
        'vas.costing.approval', 'result_version_id', string='Lịch sử duyệt',
    )

    @api.depends('period_id', 'version')
    def _compute_name(self):
        for rec in self:
            rec.name = _('KQ %(p)s v%(v)s', p=rec.period_id.name or '?', v=rec.version)

    def action_open_s18(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Thẻ S18-DNN'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'connecta_vas.view_vas_costing_result_s18_form',
            ).id,
            'target': 'current',
        }


class VasCostingResultLine(models.Model):
    _name = 'vas.costing.result.line'
    _description = 'Dòng kết quả giá thành theo đối tượng'
    _order = 'cost_object_id, id'

    version_id = fields.Many2one(
        'vas.costing.result.version', required=True, ondelete='cascade', index=True,
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', required=True, ondelete='restrict',
    )
    opening_wip = fields.Monetary(currency_field='currency_id')
    amount_direct = fields.Monetary(currency_field='currency_id')
    amount_overhead = fields.Monetary(currency_field='currency_id')
    amount_reduction = fields.Monetary(currency_field='currency_id')
    closing_wip = fields.Monetary(currency_field='currency_id')
    total_cost = fields.Monetary(currency_field='currency_id')
    amount_delivered = fields.Monetary(
        string='Đã giao thành phẩm', currency_field='currency_id', default=0.0,
        help='Phần giá thành VAS gắn thành phẩm đã giao — không lấy từ phiếu kho để ghi 155.',
    )
    amount_undelivered = fields.Monetary(
        string='Chưa giao', currency_field='currency_id', default=0.0,
        help='Phần giá thành chưa giao thành phẩm — lưu trên dòng kết quả, bắt buộc '
             'đối chiếu lưới đối tượng = đã giao + chưa giao trước khi ghi 154→155.',
    )
    stock_fg_receipt_value = fields.Monetary(
        string='Giá trị nhập TP (Odoo)', currency_field='currency_id', default=0.0,
        help='Đọc từ phiếu nhập thành phẩm vật lý — chỉ tham chiếu, không phải nguồn ghi 155.',
    )
    currency_id = fields.Many2one(related='version_id.currency_id')


class VasCostingApproval(models.Model):
    _name = 'vas.costing.approval'
    _description = 'Lịch sử duyệt giá thành'
    _order = 'id desc'

    result_version_id = fields.Many2one(
        'vas.costing.result.version', required=True, ondelete='restrict', index=True,
    )
    period_id = fields.Many2one(
        related='result_version_id.period_id', store=True, index=True,
    )
    total_cost = fields.Monetary(currency_field='currency_id')
    submitter_id = fields.Many2one('res.users', string='Người gửi duyệt', ondelete='restrict')
    reviewer_id = fields.Many2one(
        'res.users', string='Người duyệt / từ chối', ondelete='restrict',
    )
    action_date = fields.Datetime(string='Thời điểm', default=fields.Datetime.now)
    reject_reason = fields.Text(string='Lý do từ chối')
    decision = fields.Selection(
        [
            ('submitted', 'Đã gửi duyệt'),
            ('approved', 'Đã duyệt'),
            ('rejected', 'Từ chối'),
            ('revoked', 'Thu hồi duyệt'),
            ('withdrawn', 'Rút yêu cầu'),
        ],
        string='Quyết định', required=True,
    )
    effectiveness = fields.Selection(
        [('effective', 'Còn hiệu lực'), ('ineffective', 'Hết hiệu lực')],
        string='Hiệu lực lần duyệt', default='effective', required=True,
    )
    currency_id = fields.Many2one(related='result_version_id.currency_id')
    company_id = fields.Many2one(related='result_version_id.company_id', store=True)
