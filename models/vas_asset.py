# -*- coding: utf-8 -*-
import calendar
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero

from .vas_asset_schedule import (
    build_straight_line,
    build_declining,
    build_prepaid_equal,
    build_units_period_amount,
    units_rate,
)

_logger = logging.getLogger(__name__)

TSCD_MIN_VALUE = 30_000_000.0


class VasAsset(models.Model):
    _name = 'vas.asset'
    _description = 'Thẻ TSCĐ / khoản phân bổ nhiều kỳ'
    _order = 'code, id'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime', string='Chế độ', required=True, index=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    asset_type = fields.Selection(
        selection=[
            ('tscd', 'TSCĐ (khấu hao → 214)'),
            ('prepaid', 'Phân bổ 242'),
            ('deferred_revenue', 'DT chưa thực hiện (3387)'),
        ],
        required=True, default='tscd', index=True,
    )
    asset_kind = fields.Selection(
        selection=[
            ('ccdc', 'CCDC'),
            ('prepaid_service', 'Chi phí trả trước dịch vụ'),
            ('major_repair', 'Sửa chữa lớn'),
        ],
        string='Loại khoản 242',
    )
    is_welfare = fields.Boolean(
        string='TSCĐ phúc lợi (A07)',
        help='Nợ 3533 thay vì TK chi phí bộ phận.',
    )
    asset_group_id = fields.Many2one('vas.asset.group', string='Nhóm TT45 PL1')
    original_value = fields.Monetary(string='Nguyên giá / giá trị phân bổ', required=True)
    salvage_value = fields.Monetary(string='Giá trị thanh lý (optional)', default=0.0)
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    date_start = fields.Date(string='Ngày đưa vào dùng / bắt đầu PB', required=True)
    method = fields.Selection(
        selection=[
            ('straight_line', 'Đường thẳng'),
            ('declining', 'Số dư giảm dần có ĐC'),
            ('units', 'Theo sản lượng'),
        ],
        required=True, default='straight_line',
    )
    useful_life_years = fields.Float(string='Số năm KH')
    duration_months = fields.Integer(string='Số kỳ (tháng)')
    prorata = fields.Boolean(
        string='Prorata ngày (TT45 Đ9.9)',
        default=True,
        help='TSCĐ: True. Prepaid/242: luôn chia đều (engine bỏ qua).',
    )
    units_total = fields.Float(string='Sản lượng thiết kế')
    account_gross_id = fields.Many2one('vas.account', string='TK nguyên giá / 153 / 242')
    account_accum_id = fields.Many2one(
        'vas.account', string='TK hao mòn 214 / phân bổ 242', required=True,
    )
    account_expense_id = fields.Many2one('vas.account', string='TK Nợ chi phí')
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        ondelete='restrict',
        help='W12: chỉ nhận khoản mục lá (không nút tổng hợp, không CPD). '
             'Máy gắn khi sinh bút toán khấu hao.',
    )
    source_mode = fields.Selection(
        selection='_selection_source_mode',
        default='manual', required=True,
    )
    # Soft-link: Integer (không M2o account.asset) — module load được khi
    # account_asset chưa cài. Cột giữ tên odoo_asset_id (trước đây là M2o → int).
    # copy=False: tránh copy mang 0 (FK leftover / NULL→0) sang thẻ mới.
    odoo_asset_id = fields.Integer(
        string='ID tài sản Odoo',
        index=True,
        copy=False,
        help='Soft-link tới account.asset.id khi module account_asset đã cài.',
    )
    account_asset_available = fields.Boolean(
        compute='_compute_account_asset_available',
        string='Có account.asset',
    )
    acquire_move_id = fields.Many2one('vas.move', string='Bút toán ghi tăng', ondelete='set null')
    journal_id = fields.Many2one('vas.journal', string='Sổ nhật ký')
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('running', 'Đang chạy'),
            ('paused', 'Tạm dừng'),
            ('closed', 'Đã hết'),
            ('cancelled', 'Đã hủy'),
        ],
        default='draft', required=True, index=True, copy=False,
    )
    line_ids = fields.One2many('vas.asset.line', 'asset_id', string='Lịch')
    value_depreciated = fields.Monetary(
        compute='_compute_value_stats', string='Đã trích/phân bổ',
    )
    value_residual = fields.Monetary(
        compute='_compute_value_stats', string='Còn lại',
    )
    warning_note = fields.Text(string='Cảnh báo', copy=False)

    _sql_constraints = [
        (
            'code_company_uniq',
            'unique(code, company_id)',
            'Mã thẻ tài sản phải duy nhất trong công ty.',
        ),
    ]

    def init(self):
        """Gỡ FK leftover khi odoo_asset_id từng là M2o account.asset; 0 → NULL."""
        self.env.cr.execute(
            'ALTER TABLE vas_asset DROP CONSTRAINT IF EXISTS vas_asset_odoo_asset_id_fkey'
        )
        self.env.cr.execute(
            'UPDATE vas_asset SET odoo_asset_id = NULL WHERE odoo_asset_id = 0'
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('odoo_asset_id'):
                vals['odoo_asset_id'] = False
        return super().create(vals_list)

    def write(self, vals):
        if 'odoo_asset_id' in vals and not vals.get('odoo_asset_id'):
            vals = dict(vals, odoo_asset_id=False)
        return super().write(vals)

    @api.model
    def _account_asset_model_available(self):
        """True khi registry có model account.asset (module account_asset đã cài)."""
        return 'account.asset' in self.env

    @api.model
    def _selection_source_mode(self):
        modes = [('manual', _('Nhập tay'))]
        if self._account_asset_model_available():
            modes.append(('odoo_asset', _('Đọc account.asset')))
        return modes

    @api.depends_context('uid')
    def _compute_account_asset_available(self):
        avail = self._account_asset_model_available()
        for asset in self:
            asset.account_asset_available = avail

    def _browse_odoo_asset(self):
        """Trả recordset account.asset đã exists, hoặc recordset rỗng / False."""
        self.ensure_one()
        if not self._account_asset_model_available():
            return False
        if not self.odoo_asset_id:
            return self.env['account.asset'].browse()
        return self.env['account.asset'].browse(self.odoo_asset_id).exists()

    @api.constrains('source_mode', 'odoo_asset_id')
    def _check_source_mode_odoo_asset(self):
        for asset in self:
            if asset.source_mode != 'odoo_asset':
                continue
            if not asset._account_asset_model_available():
                raise ValidationError(_(
                    'source_mode=odoo_asset yêu cầu module account_asset. '
                    'Dùng nhập tay (manual) hoặc cài account_asset.'
                ))
            if not asset.odoo_asset_id:
                raise ValidationError(_(
                    'source_mode=odoo_asset cần ID tài sản Odoo (odoo_asset_id).'
                ))
            if not asset._browse_odoo_asset():
                raise ValidationError(_(
                    'Không tìm thấy account.asset id=%s.'
                ) % asset.odoo_asset_id)

    @api.constrains('cost_item_id')
    def _check_cost_item_leaf_not_cpd(self):
        for asset in self:
            item = asset.cost_item_id
            if not item:
                continue
            if item.is_aggregate_node:
                raise ValidationError(_(
                    'Thẻ tài sản chỉ nhận khoản mục lá. '
                    '«%(code)s — %(name)s» là nút tổng hợp.',
                    code=item.code or '',
                    name=item.name or '',
                ))
            if item._is_cpd_seed():
                raise ValidationError(_(
                    'Không được khai khoản mục «Chưa phân loại» (CPD) trên '
                    'thẻ tài sản. CPD chỉ dùng khi máy tra không ra.'
                ))

    @api.depends('line_ids.amount', 'line_ids.state', 'original_value', 'salvage_value')
    def _compute_value_stats(self):
        for asset in self:
            posted = sum(
                line.amount for line in asset.line_ids if line.state == 'posted'
            )
            # KH full NG (salvage default 0, optional field kept)
            base = asset.original_value
            asset.value_depreciated = posted
            asset.value_residual = base - posted

    def _depreciable_base(self):
        """Full nguyên giá — salvage không trừ (quyết định §8)."""
        self.ensure_one()
        return self.original_value

    def _expense_account(self, fallbacks=None):
        self.ensure_one()
        if self.is_welfare:
            acc = self.env['vas.account'].search([
                ('regime_id', '=', self.regime_id.id),
                ('code', '=', '3533'),
            ], limit=1)
            return acc
        if self.account_expense_id:
            return self.account_expense_id
        acc = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id),
            ('code', '=', '6422'),
        ], limit=1)
        if fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'thẻ tài sản %(asset)s — chưa khai TK chi phí (bộ phận sử dụng), '
                    'dùng mặc định 6422',
                    asset='%s (%s)' % (self.code, self.name),
                ),
            })
        return acc

    def _resolve_cost_item(self, cost_fallbacks=None):
        """Khoản mục khi sinh KH; thiếu → CPD + fallback (cờ unclassified)."""
        self.ensure_one()
        if self.cost_item_id:
            return self.cost_item_id
        cpd = self.env['vas.cost.item']._system_by_code(self.company_id, 'CPD')
        if cost_fallbacks is not None:
            cost_fallbacks.append({
                'source': 'asset',
                'label': _(
                    'thẻ tài sản %(asset)s → khoản mục Chưa phân loại (CPD)',
                    asset=self.display_name,
                ),
            })
        return cpd

    def _default_journal(self):
        self.ensure_one()
        if self.journal_id:
            return self.journal_id
        return self.env['vas.journal'].search([
            ('code', '=', 'TH'),
            ('company_id', '=', self.company_id.id),
        ], limit=1) or self.env['vas.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _move_kind(self):
        self.ensure_one()
        if self.asset_type == 'tscd':
            return 'depreciation'
        return 'prepaid_alloc'

    # -------------------------------------------------------------------------
    # Warnings (Đ3 + PL1) — không chặn
    # -------------------------------------------------------------------------

    def _collect_warnings(self):
        self.ensure_one()
        notes = []
        if self.asset_type == 'tscd':
            years = self.useful_life_years or (
                (self.duration_months or 0) / 12.0
            )
            if self.original_value < TSCD_MIN_VALUE or years <= 1.0:
                notes.append(_(
                    'TT45 Đ3: TSCĐ thường ≥ 30.000.000đ và thời gian > 1 năm. '
                    'Thẻ hiện tại NG=%(ng)s, năm=%(y)s — kiểm tra lại '
                    '(có thể là CCDC/242).',
                    ng=self.original_value, y=years,
                ))
            group = self.asset_group_id
            if group and group.min_years and group.max_years and years:
                if years < group.min_years or years > group.max_years:
                    notes.append(_(
                        'Phụ lục 1: số năm %(y)s ngoài khung [%(mn)s–%(mx)s] '
                        'của nhóm %(g)s (chỉ cảnh báo).',
                        y=years, mn=group.min_years, mx=group.max_years,
                        g=group.display_name,
                    ))
        if self.is_welfare:
            fund = self.env['vas.account'].search([
                ('regime_id', '=', self.regime_id.id), ('code', '=', '3533'),
            ], limit=1)
            if fund:
                # Soft: compute posted balance if ledger helpers exist; else skip
                notes.append(_(
                    'A07 phúc lợi: Nợ 3533 — kiểm tra quỹ đủ trước khi sinh kỳ '
                    '(cảnh báo, không chặn).'
                ))
        return notes

    def _refresh_warnings(self):
        for asset in self:
            notes = asset._collect_warnings()
            asset.warning_note = '\n'.join(notes) if notes else False

    # -------------------------------------------------------------------------
    # Period helpers
    # -------------------------------------------------------------------------

    def _ensure_period_for_date(self, day):
        """Period phủ ``day`` — tự trải theo quy tắc niên độ công ty."""
        self.ensure_one()
        Period = self.env['vas.period']
        period = Period._ensure_covering_period(self.company_id, day)
        if period:
            return period
        Period._raise_missing_period(
            self.company_id, day, doc_name=self.display_name,
        )

    # -------------------------------------------------------------------------
    # Schedule
    # -------------------------------------------------------------------------

    def action_recompute_schedule(self):
        """Tính lại dòng planned; giữ posted."""
        for asset in self:
            asset._recompute_schedule()
        return True

    def _recompute_schedule(self):
        self.ensure_one()
        posted = self.line_ids.filtered(lambda l: l.state == 'posted')
        planned = self.line_ids.filtered(lambda l: l.state == 'planned')
        planned.unlink()

        depreciable = self._depreciable_base()
        posted_sum = sum(posted.mapped('amount'))
        residual = depreciable - posted_sum

        if self.method == 'units':
            # Không pre-gen; planned tạo khi nhập units_qty.
            self._refresh_warnings()
            return

        if residual <= 0 and posted:
            self._refresh_warnings()
            return

        if self.asset_type == 'prepaid':
            n = self.duration_months or 0
            if posted:
                last_posted = posted.sorted('sequence')[-1]
                start = last_posted.date_to + relativedelta(days=1)
                n_left = max(n - len(posted), 1)
                raw = build_prepaid_equal(residual, n_left, start)
            else:
                raw = build_prepaid_equal(
                    depreciable, self.duration_months or 1, self.date_start,
                )
        elif self.method == 'declining':
            if posted:
                months_done = len(posted)
                months_total = int(round((self.useful_life_years or 1) * 12))
                months_left = max(months_total - months_done, 1)
                start = posted.sorted('sequence')[-1].date_to + relativedelta(days=1)
                raw = build_straight_line(
                    residual, months_left / 12.0, start, prorata=False,
                )
            else:
                raw = build_declining(
                    depreciable,
                    int(self.useful_life_years or 1),
                    self.date_start,
                    prorata=self.prorata,
                )
        else:
            # straight_line TSCĐ
            if posted:
                months_total = self.duration_months or int(
                    round((self.useful_life_years or 0) * 12)
                )
                months_left = max(months_total - len(posted), 1)
                start = posted.sorted('sequence')[-1].date_to + relativedelta(days=1)
                raw = build_straight_line(
                    residual, months_left / 12.0, start, prorata=False,
                )
            else:
                years = self.useful_life_years or (
                    (self.duration_months or 12) / 12.0
                )
                raw = build_straight_line(
                    depreciable, years, self.date_start, prorata=self.prorata,
                )

        seq_base = max(posted.mapped('sequence') or [0])
        for vals in raw:
            period = self._ensure_period_for_date(vals['date_to'])
            vals = dict(vals)
            vals['sequence'] = seq_base + vals['sequence']
            vals['asset_id'] = self.id
            vals['period_id'] = period.id
            # avoid unique clash if period already has posted
            exists = self.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'posted'
            )
            if exists:
                continue
            self.env['vas.asset.line'].create(vals)
        self._refresh_warnings()

    def action_confirm(self):
        """draft → running + sinh lịch.

        Lịch phải dựng XONG mới đổi state. Lỗi giữa chừng (thiếu quy tắc niên độ…)
        → savepoint rollback toàn bộ dòng lịch; state giữ draft.
        Nguyên nhân vòng 1: ``state='running'`` gán TRƯỚC ``_recompute_schedule``,
        không savepoint → RedirectWarning giữa vòng để lại 10 line + running.
        """
        for asset in self:
            if asset.state != 'draft':
                continue
            if not asset.duration_months and asset.useful_life_years:
                asset.duration_months = int(round(asset.useful_life_years * 12))
            if not asset.useful_life_years and asset.duration_months:
                asset.useful_life_years = asset.duration_months / 12.0
            # Không tự điền 6422 im lặng — _post_line rơi 6422 + cờ mặc định.
            # Trải trước toàn bộ kỳ cần cho lịch (chung helper với loan)
            if asset.method != 'units' and asset.date_start:
                years = asset.useful_life_years or (
                    (asset.duration_months or 12) / 12.0
                )
                # bound trên: date_start + useful life (+1 tháng đệm prorata)
                end_hint = asset.date_start + relativedelta(
                    years=int(years) + 1, months=1,
                )
                self.env['vas.period']._ensure_periods_covering_range(
                    asset.company_id,
                    asset.date_start,
                    end_hint,
                    doc_name=asset.display_name,
                )
            with self.env.cr.savepoint():
                asset._recompute_schedule()
                asset.state = 'running'
            asset._refresh_warnings()
        return True

    def action_cancel(self):
        for asset in self:
            asset.line_ids.filtered(lambda l: l.state == 'planned').write({
                'state': 'skipped',
            })
            for line in asset.line_ids.filtered(lambda l: l.state == 'posted'):
                move = line.move_id
                if not move or move.state in ('reversed', 'cancelled'):
                    continue
                if self.env['vas.period']._date_in_closed_period(
                    move.company_id, move.date,
                ):
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                else:
                    move.action_reverse()
                    line.state = 'skipped'
            asset.state = 'cancelled'
        return True

    def action_sync_odoo_master(self):
        """Nút tay: đọc master account.asset — KHÔNG copy board KH."""
        if not self._account_asset_model_available():
            raise UserError(_(
                'Module account_asset chưa cài. Chỉ dùng nhập tay (source_mode=manual).'
            ))
        for asset in self:
            odoo = asset._browse_odoo_asset()
            if not odoo:
                raise UserError(_('Chưa gắn / không tìm thấy account.asset.'))
            vals = {
                'source_mode': 'odoo_asset',
                'original_value': odoo.original_value,
                'date_start': odoo.prorata_date or odoo.acquisition_date,
            }
            method = getattr(odoo, 'method', 'linear')
            if method in ('degressive', 'degressive_then_linear'):
                vals['method'] = 'declining'
            else:
                vals['method'] = 'straight_line'
            number = int(getattr(odoo, 'method_number', 0) or 0)
            period = str(getattr(odoo, 'method_period', '1') or '1')
            if period == '12':
                vals['useful_life_years'] = float(number)
                vals['duration_months'] = number * 12
            else:
                vals['duration_months'] = number
                vals['useful_life_years'] = number / 12.0
            asset.write(vals)
            if asset.state == 'running':
                asset._recompute_schedule()
            asset._refresh_warnings()
        return True

    def action_set_units_qty(self, period, qty, is_last=False):
        """Units method: tạo/cập nhật line planned cho kỳ rồi chờ post."""
        self.ensure_one()
        if self.method != 'units':
            raise UserError(_('Chỉ dùng cho method=units.'))
        if self.state != 'running':
            raise UserError(_('Thẻ phải ở trạng thái Đang chạy.'))
        period = period if period._name == 'vas.period' else self.env['vas.period'].browse(period)
        line = self.line_ids.filtered(lambda l: l.period_id == period)[:1]
        residual = self.value_residual
        amount = build_units_period_amount(
            self._depreciable_base(), self.units_total, qty, residual, is_last=is_last,
        )
        dim = calendar.monthrange(period.date_end.year, period.date_end.month)[1]
        vals = {
            'units_qty': qty,
            'amount': amount,
            'date_from': period.date_start,
            'date_to': period.date_end,
            'date': period.date_end,
            'days': dim,
            'days_in_month': dim,
            'is_last': is_last,
        }
        if line:
            if line.state == 'posted':
                raise UserError(_('Kỳ đã ghi sổ, không sửa sản lượng.'))
            line.write(vals)
        else:
            seq = max(self.line_ids.mapped('sequence') or [0]) + 1
            posted_sum = sum(self.line_ids.filtered(lambda l: l.state == 'posted').mapped('amount'))
            accum = posted_sum + amount
            self.env['vas.asset.line'].create({
                **vals,
                'asset_id': self.id,
                'period_id': period.id,
                'sequence': seq,
                'accumulated': accum,
                'remaining': self._depreciable_base() - accum,
                'state': 'planned',
            })
        return True

    # -------------------------------------------------------------------------
    # CCDC issue (A09-1 / A09-2) — event, không trong pass kỳ T
    # -------------------------------------------------------------------------

    def action_issue_ccdc_once(self, amount=None):
        """A09-1: Nợ CP / Có 153."""
        self.ensure_one()
        amount = amount if amount is not None else self.original_value
        return self._create_ccdc_issue_move(amount, mode='once')

    def action_issue_ccdc_multi(self, amount=None, duration_months=None):
        """A09-2: Nợ 242 / Có 153 + chuyển thẻ prepaid + lịch."""
        self.ensure_one()
        amount = amount if amount is not None else self.original_value
        move = self._create_ccdc_issue_move(amount, mode='multi')
        self.write({
            'asset_type': 'prepaid',
            'asset_kind': 'ccdc',
            'method': 'straight_line',
            'prorata': False,
            'duration_months': duration_months or self.duration_months or 12,
            'original_value': amount,
            'account_accum_id': self.env['vas.account'].search([
                ('regime_id', '=', self.regime_id.id), ('code', '=', '242'),
            ], limit=1).id or self.account_accum_id.id,
            'state': 'draft',
        })
        self.action_confirm()
        return move

    def _create_ccdc_issue_move(self, amount, mode='once'):
        self.ensure_one()
        expense = self._expense_account()
        acc_153 = self.account_gross_id or self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '153'),
        ], limit=1)
        acc_242 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '242'),
        ], limit=1)
        if mode == 'once':
            debit_acc = expense
        else:
            debit_acc = acc_242
        if not debit_acc or not acc_153:
            raise UserError(_('Thiếu TK chi phí hoặc 153/242.'))
        journal = self._default_journal()
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS.'))
        kind = 'ccdc_issue'
        move = self.env['vas.move'].create({
            'date': self.date_start,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': kind,
            'ref': _('Xuất CCDC %s') % self.display_name,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.code,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'account_id': debit_acc.id,
                    'name': self.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                Command.create({
                    'sequence': 20, 'account_id': acc_153.id,
                    'name': self.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.action_post()
        return move

    # -------------------------------------------------------------------------
    # Pass sinh kỳ
    # -------------------------------------------------------------------------

    @api.model
    def generate_asset_entries(self, company, period):
        """Sinh bút toán KH/phân bổ cho mọi thẻ running trong kỳ.

        Idempotent. Kỳ closed → UserError. Units thiếu qty → skip + warn.
        """
        if period.state == 'closed':
            raise UserError(_(
                'Kỳ %(p)s đã khóa — không sinh khấu hao/phân bổ.',
                p=period.display_name,
            ))
        assets = self.search([
            ('company_id', '=', company.id),
            ('state', '=', 'running'),
            ('date_start', '<=', period.date_end),
        ])
        stats = {'created': 0, 'skipped': 0, 'warnings': []}
        for asset in assets:
            line = asset.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'planned'
            )[:1]
            if not line:
                stats['skipped'] += 1
                continue
            if asset.method == 'units' and float_is_zero(line.units_qty, 5):
                msg = _(
                    '%(a)s kỳ %(p)s: chưa nhập sản lượng — bỏ qua.',
                    a=asset.display_name, p=period.display_name,
                )
                stats['warnings'].append(msg)
                _logger.warning('VAS asset units: %s', msg)
                stats['skipped'] += 1
                continue
            if line.move_id:
                stats['skipped'] += 1
                continue
            # welfare fund soft warning
            if asset.is_welfare:
                asset._refresh_warnings()
            move = asset._post_line(line)
            if move:
                stats['created'] += 1
            else:
                stats['skipped'] += 1
        return stats

    def _post_line(self, line):
        self.ensure_one()
        if line.state != 'planned':
            return self.env['vas.move']
        if line.move_id:
            return line.move_id
        acc_fallbacks = []
        expense = self._expense_account(acc_fallbacks)
        accum = self.account_accum_id
        origin = self.env['vas.capital.in.kind'].search([
            ('asset_id', '=', self.id),
        ], limit=1)
        if origin and not self.account_expense_id and accum and (
            accum.code or ''
        ) in ('2141', '214'):
            acc_fallbacks.append({
                'label': _(
                    'thẻ tài sản %(asset)s (phiếu góp vốn %(cap)s) — chưa khai '
                    'TK hao mòn, dùng mặc định %(code)s',
                    asset='%s (%s)' % (self.code, self.name),
                    cap=origin.ref or origin.name or origin.display_name,
                    code=accum.code,
                ),
            })
        if not expense or not accum:
            raise UserError(_(
                'Thẻ %(a)s thiếu TK chi phí hoặc TK 214/242.',
                a=self.display_name,
            ))
        journal = self._default_journal()
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS (TH/general).'))
        kind = self._move_kind()
        # idempotency via vas.move unique constraint
        existing = self.env['vas.move'].search([
            ('source_model', '=', 'vas.asset.line'),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', kind),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            line.write({'move_id': existing.id, 'state': 'posted'})
            return existing

        amount = line.amount
        if float_is_zero(amount, 2):
            line.state = 'skipped'
            return self.env['vas.move']

        cost_fallbacks = []
        cost_item = self._resolve_cost_item(cost_fallbacks)
        expense_line = {
            'sequence': 10, 'account_id': expense.id,
            'name': self.name, 'debit': amount, 'credit': 0.0,
            'currency_id': self.currency_id.id,
        }
        if cost_item:
            expense_line['cost_item_id'] = cost_item.id
        move_vals = {
            'date': line.date or line.period_id.date_end,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': kind,
            'ref': _('%s — %s') % (self.display_name, line.period_id.display_name),
            'source_model': 'vas.asset.line',
            'source_res_id': line.id,
            'source_ref': '%s/%s' % (self.code, line.period_id.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                Command.create(expense_line),
                Command.create({
                    'sequence': 20, 'account_id': accum.id,
                    'name': self.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': self.currency_id.id,
                }),
            ],
            **self.env['vas.sync']._merge_move_flag_vals(
                self.env['vas.sync']._default_account_flag_vals(acc_fallbacks),
                self.env['vas.sync']._unclassified_cost_flag_vals(cost_fallbacks),
            ),
        }
        move = self.env['vas.move'].create(move_vals)
        move.action_post()
        line.write({'move_id': move.id, 'state': 'posted'})
        if line.is_last or not self.line_ids.filtered(lambda l: l.state == 'planned'):
            if not self.line_ids.filtered(lambda l: l.state == 'planned'):
                self.state = 'closed'
        return move

    def action_generate_period_entries(self):
        """Nút tay trên thẻ: sinh JE cho các line planned đã tới hạn (kỳ mở)."""
        for asset in self:
            lines = asset.line_ids.filtered(
                lambda l: l.state == 'planned'
                and l.period_id
                and l.period_id.state != 'closed'
                and l.period_id.date_end >= asset.date_start
            )
            for line in lines:
                if asset.method == 'units' and float_is_zero(line.units_qty, 5):
                    continue
                asset._post_line(line)
        return True


class VasAssetLine(models.Model):
    _name = 'vas.asset.line'
    _description = 'Dòng lịch khấu hao / phân bổ'
    _order = 'asset_id, sequence, id'

    asset_id = fields.Many2one(
        'vas.asset', required=True, index=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=1)
    period_id = fields.Many2one('vas.period', required=True, index=True)
    date = fields.Date(string='Ngày ghi sổ')
    date_from = fields.Date()
    date_to = fields.Date()
    days = fields.Integer()
    days_in_month = fields.Integer()
    amount = fields.Monetary()
    accumulated = fields.Monetary(string='Lũy kế')
    remaining = fields.Monetary(string='Còn lại')
    units_qty = fields.Float(string='Sản lượng kỳ')
    state = fields.Selection(
        selection=[
            ('planned', 'Chưa ghi'),
            ('posted', 'Đã ghi'),
            ('skipped', 'Bỏ qua'),
        ],
        default='planned', required=True, index=True,
    )
    move_id = fields.Many2one('vas.move', string='Bút toán', ondelete='set null')
    is_last = fields.Boolean(string='Kỳ cuối')
    currency_id = fields.Many2one(
        related='asset_id.currency_id', store=True,
    )
    company_id = fields.Many2one(
        related='asset_id.company_id', store=True, index=True,
    )

    _sql_constraints = [
        (
            'asset_period_uniq',
            'unique(asset_id, period_id)',
            'Mỗi thẻ chỉ một dòng lịch cho một kỳ.',
        ),
    ]
