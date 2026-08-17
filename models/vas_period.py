# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import date_utils
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)


class VasPeriod(models.Model):
    _name = 'vas.period'
    _description = 'Kỳ kế toán VAS'
    _order = 'date_start, id'

    name = fields.Char(string='Tên', required=True)
    date_start = fields.Date(string='Ngày bắt đầu', required=True)
    date_end = fields.Date(string='Ngày kết thúc', required=True)
    fiscalyear_id = fields.Many2one(
        'vas.fiscalyear',
        string='Năm tài chính',
        required=True,
        index=True,
        ondelete='cascade',
    )
    state = fields.Selection(
        selection=[
            ('open', 'Đang mở'),
            ('closed', 'Đã khóa'),
        ],
        string='Trạng thái',
        required=True,
        default='open',
        index=True,
        help='Closed periods reject new journal entries.',
    )
    quarter = fields.Integer(
        string='Quý',
        compute='_compute_quarter',
        store=True,
        help='Calendar quarter 1–4 derived from date_start.',
    )

    @api.depends('date_start')
    def _compute_quarter(self):
        for period in self:
            if period.date_start:
                period.quarter = (period.date_start.month - 1) // 3 + 1
            else:
                period.quarter = 0

    # -------------------------------------------------------------------------
    # W9.5 — helper dùng chung theo NGÀY (không tin period_id stored)
    #
    # ``missing`` = công ty CHƯA có quy tắc niên độ (không trải được kỳ)
    #            → LUÔN «KHÔNG ĐƯỢC». Khác closed.
    # Có quy tắc (tái dùng res.company.fiscalyear_last_day/month) → tự dựng
    # bản ghi kỳ/niên độ theo đúng quy tắc, state=open.
    # -------------------------------------------------------------------------

    @api.model
    def _has_fiscal_year_rule(self, company):
        """Công ty đã có quy tắc niên độ dùng được (Odoo account fields)."""
        if self.env.context.get('vas_force_no_fiscal_rule'):
            return False
        if not company:
            return False
        if 'fiscalyear_last_day' not in company._fields:
            return False
        if 'fiscalyear_last_month' not in company._fields:
            return False
        return bool(company.fiscalyear_last_day and company.fiscalyear_last_month)

    @api.model
    def _fiscal_year_bounds(self, company, day):
        """(date_from, date_to) niên độ chứa ``day`` theo quy tắc công ty."""
        last_day = company.fiscalyear_last_day
        last_month = int(company.fiscalyear_last_month)
        return date_utils.get_fiscal_year(day, day=last_day, month=last_month)

    @api.model
    def _period_covering(self, company, day):
        """Period phủ ``day`` của ``company``, hoặc empty recordset (không tự dựng)."""
        if not day or not company:
            return self.browse()
        return self.search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '<=', day),
            ('date_end', '>=', day),
        ], limit=1)

    @api.model
    def _ensure_covering_period(self, company, day):
        """Period phủ ``day``; tự trải kỳ/niên độ theo quy tắc nếu thiếu bản ghi.

        Trả empty khi không có quy tắc niên độ (→ missing). Không đẻ kỳ chồng:
        reuse ``action_generate_periods`` + create idempotent + constraint §8.7.
        """
        if not day or not company:
            return self.browse()
        period = self._period_covering(company, day)
        if period:
            return period
        if not self._has_fiscal_year_rule(company):
            return self.browse()

        date_from, date_to = self._fiscal_year_bounds(company, day)
        FY = self.env['vas.fiscalyear']
        fy = FY.search([
            ('company_id', '=', company.id),
            ('date_from', '<=', day),
            ('date_to', '>=', day),
        ], limit=1)
        if not fy:
            if date_from.year == date_to.year:
                fy_name = str(date_from.year)
            else:
                fy_name = '%s-%s' % (date_from.year, date_to.year)
            fy = FY.create({
                'name': fy_name,
                'date_from': date_from,
                'date_to': date_to,
                'company_id': company.id,
                'state': 'open',
            })
            _logger.warning(
                'VAS W9.5: TỰ DỰNG NIÊN ĐỘ MỚI company=%s(%s) fy=%s %s..%s '
                '(kích hoạt bởi ngày %s) — kiểm tra nếu niên độ này bất thường',
                company.id, company.display_name, fy.name,
                date_from, date_to, day,
            )
        else:
            before = len(fy.period_ids)
            fy.action_generate_periods()
            after = len(fy.period_ids)
            if after > before:
                _logger.info(
                    'VAS W9.5: tự trải kỳ trên niên độ có sẵn company=%s fy=%s '
                    'periods %s→%s (ngày %s)',
                    company.id, fy.display_name, before, after, day,
                )
            else:
                _logger.info(
                    'VAS W9.5: niên độ %s đã đủ kỳ; tìm lại kỳ phủ ngày %s',
                    fy.display_name, day,
                )
        return self._period_covering(company, day)

    @api.model
    def _ensure_periods_covering_range(self, company, date_from, date_to, *, doc_name=None):
        """Tự trải mọi kỳ phủ [date_from, date_to]. Thiếu quy tắc / lỗ → UserError."""
        if not date_from:
            raise UserError(_('Thiếu ngày bắt đầu khi dựng lịch kỳ VAS.'))
        if not date_to:
            date_to = date_from
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        if not self._has_fiscal_year_rule(company):
            self._raise_missing_period(company, date_from, doc_name=doc_name)
        cursor = date_from
        while cursor <= date_to:
            period = self._ensure_covering_period(company, cursor)
            if not period:
                self._raise_missing_period(company, cursor, doc_name=doc_name)
            cursor = period.date_end + relativedelta(days=1)
        return True

    @api.model
    def _coverage_status(self, company, day):
        """`'missing'` | `'open'` | `'closed'`.

        Có quy tắc niên độ → tự trải kỳ rồi trả state.
        ``missing`` = chưa khai quy tắc (không trải được) — KHÔNG ĐƯỢC ghi sổ.
        """
        period = self._ensure_covering_period(company, day)
        if not period:
            return 'missing'
        return period.state  # 'open' | 'closed'

    @api.model
    def _date_in_closed_period(self, company, day):
        return self._coverage_status(company, day) == 'closed'

    @api.model
    def _is_opening_balance_exempt(self, move):
        """True nếu move là số dư đầu kỳ (hoặc đảo của nó).

        Chỉ tin ``source_model == 'vas.opening.balance'`` trên gốc.
        Đảo: truy ngược ``search([('reversal_move_id', '=', move.id)])`` rồi
        xét ``source_model`` của gốc.

        CẤM rút gọn về ``move_kind == 'opening'`` hoặc journal MOSO:
        form tạo tay cho chọn ``move_kind='opening'`` (A4) → cửa lách cutoff.
        """
        if not move:
            return False
        if move.source_model == 'vas.opening.balance':
            return True
        if move.is_reversal:
            origin = self.env['vas.move'].search([
                ('reversal_move_id', '=', move.id),
            ], limit=1)
            return bool(origin and origin.source_model == 'vas.opening.balance')
        return False

    @api.model
    def _assert_date_writable(
        self, company, day, *, doc_name=None, allow_missing=False, move=None,
    ):
        """Chặn ghi sổ khi missing (trừ draft), closed, hoặc vi phạm cutoff.

        Message VI đủ 4 phần (§8.6): ngày + số chứng từ + lý do + việc cần làm.
        ``allow_missing=True``: chỉ chặn closed (create/sửa nháp §8.4) —
        **không** áp cutoff (nháp ngày trước mốc / cutoff trống vẫn tạo được).
        ``allow_missing=False`` (post): cutoff trống hoặc ``day < cutoff`` → chặn,
        trừ miễn trừ số dư đầu kỳ (§ ``_is_opening_balance_exempt``).
        """
        doc = doc_name or _('(chưa có số)')
        day_s = day and fields.Date.to_string(day) or _('(không có ngày)')
        # Cutoff cứng lúc POST — thiếu mốc = không được (như missing kỳ W9.5).
        if not allow_missing and company:
            if not company.vas_start_date:
                raise UserError(_(
                    "Ngày: %(date)s\n"
                    "Số chứng từ: %(doc)s\n"
                    "Lý do: công ty chưa khai ngày bắt đầu ghi sổ VAS.\n"
                    "Việc cần làm: vào Cài đặt → Connecta VAS, khai ngày bắt đầu "
                    "ghi sổ, rồi ghi sổ lại.",
                    date=day_s,
                    doc=doc,
                ))
            # Biểu thức so sánh: day_d < cutoff  (không dùng <=)
            if day and not self._is_opening_balance_exempt(move):
                cutoff = fields.Date.to_date(company.vas_start_date)
                day_d = fields.Date.to_date(day)
                if day_d < cutoff:
                    raise UserError(_(
                        "Ngày: %(date)s\n"
                        "Số chứng từ: %(doc)s\n"
                        "Lý do: ngày chứng từ trước ngày bắt đầu ghi sổ "
                        "(%(cutoff)s) — thuộc phạm vi số dư đầu kỳ; "
                        "ghi thêm sẽ cộng trùng số dư.\n"
                        "Việc cần làm: đổi ngày từ %(cutoff)s trở đi, hoặc "
                        "điều chỉnh số dư đầu kỳ (mở sổ) thay vì ghi sổ tay "
                        "trước mốc.",
                        date=day_s,
                        doc=doc,
                        cutoff=fields.Date.to_string(cutoff),
                    ))
        status = self._coverage_status(company, day)
        if status == 'closed':
            period = self._period_covering(company, day)
            raise UserError(_(
                "Ngày: %(date)s\n"
                "Số chứng từ: %(doc)s\n"
                "Lý do: kỳ kế toán «%(period)s» đã khóa sổ.\n"
                "Việc cần làm: mở lại kỳ (nếu được phép) hoặc ghi vào kỳ đang mở; "
                "không sửa/đảo tự động trong kỳ đã khóa.",
                date=day_s,
                doc=doc,
                period=period.display_name,
            ))
        if status == 'missing' and not allow_missing:
            self._raise_missing_period(company, day, doc_name=doc)
        return True

    @api.model
    def _raise_missing_period(self, company, day, *, doc_name=None):
        """UserError khi missing = chưa khai quy tắc niên độ (không RedirectWarning)."""
        doc = doc_name or _('(chưa có số)')
        day_s = day and fields.Date.to_string(day) or _('(không có ngày)')
        raise UserError(_(
            "Ngày: %(date)s\n"
            "Số chứng từ: %(doc)s\n"
            "Lý do: công ty chưa khai quy tắc niên độ kế toán "
            "(tháng/ngày kết thúc năm tài chính) — không thể tự trải kỳ VAS.\n"
            "Việc cần làm: khai kết thúc năm tài chính trên công ty "
            "(mặc định 31/12 — năm dương lịch), rồi ghi sổ / đồng bộ lại.",
            date=day_s,
            doc=doc,
        ))

    def _assign_orphan_moves(self):
        """Gán period_id cho move mồ côi có date trong khoảng kỳ. Trả về số đã gán."""
        Move = self.env['vas.move']
        total = 0
        for period in self:
            company = period.fiscalyear_id.company_id
            orphans = Move.search([
                ('company_id', '=', company.id),
                ('date', '>=', period.date_start),
                ('date', '<=', period.date_end),
                ('period_id', '=', False),
            ])
            if not orphans:
                continue
            orphans.with_context(
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({'period_id': period.id})
            total += len(orphans)
            _logger.info(
                'VAS W9.5: gán period_id=%s (%s) cho %s move mồ côi (date %s..%s)',
                period.id, period.display_name, len(orphans),
                period.date_start, period.date_end,
            )
        return total

    def _posted_moves_in_date_range(self, extra_domain=None):
        """Posted moves theo NGÀY trong kỳ (không tin period_id)."""
        self.ensure_one()
        company = self.fiscalyear_id.company_id
        domain = [
            ('company_id', '=', company.id),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('state', '=', 'posted'),
        ]
        if extra_domain:
            domain = domain + list(extra_domain)
        return self.env['vas.move'].search(domain)

    @api.model_create_multi
    def create(self, vals_list):
        """Idempotent theo (company, date_start, date_end): trùng khoảng → trả kỳ có sẵn.

        Tránh nổ khi FY auto-sinh kỳ rồi code/test gọi create cùng tháng (§8.1a).
        Chồng lệch ngày vẫn ValidationError ở constraint.
        """
        to_create = []
        existing = self.browse()
        for vals in vals_list:
            fy = self.env['vas.fiscalyear'].browse(vals.get('fiscalyear_id'))
            company = fy.company_id if fy else self.env.company
            ds, de = vals.get('date_start'), vals.get('date_end')
            found = self.browse()
            if ds and de and company:
                found = self.search([
                    ('fiscalyear_id.company_id', '=', company.id),
                    ('date_start', '=', ds),
                    ('date_end', '=', de),
                ], limit=1)
            if found:
                existing |= found
            else:
                to_create.append(vals)
        created = super().create(to_create) if to_create else self.browse()
        result = created | existing
        result._assign_orphan_moves()
        return result

    def write(self, vals):
        if vals.get('state') == 'closed':
            closing = self.filtered(lambda p: p.state != 'closed')
            # Q2: tự gán mồ côi trước mọi kiểm tra đóng kỳ
            assigned = closing._assign_orphan_moves()
            if assigned:
                _logger.info(
                    'VAS W9.5: đóng kỳ — đã tự gán %s move mồ côi trước kiểm tra',
                    assigned,
                )
            closing._check_no_pos_rounding_gap()
            closing._check_no_default_account_move()
            closing._check_no_unclassified_cost_move()
            closing._check_no_unvalued_stock_move()
            if not self.env.context.get('vas_skip_asset_lock_check'):
                closing._check_no_pending_asset_lines()
                closing._check_no_pending_loan_lines()
            closing._check_no_open_pl_balance()
        return super().write(vals)

    @api.constrains('date_start', 'date_end', 'fiscalyear_id')
    def _check_no_overlap_same_company(self):
        """§8.7: không chồng khoảng kỳ trong cùng công ty."""
        for period in self:
            if not period.date_start or not period.date_end or not period.fiscalyear_id:
                continue
            company = period.fiscalyear_id.company_id
            rivals = self.search([
                ('id', '!=', period.id),
                ('fiscalyear_id.company_id', '=', company.id),
                ('date_start', '<=', period.date_end),
                ('date_end', '>=', period.date_start),
            ], limit=1)
            if rivals:
                raise ValidationError(_(
                    "Ngày: %(start)s – %(end)s\n"
                    "Số chứng từ: kỳ «%(name)s»\n"
                    "Lý do: khoảng ngày chồng với kỳ «%(other)s» cùng công ty.\n"
                    "Việc cần làm: chỉnh ngày bắt đầu/kết thúc để các kỳ không chồng nhau.",
                    start=period.date_start,
                    end=period.date_end,
                    name=period.display_name,
                    other=rivals.display_name,
                ))

    def _unmapped_payroll_departments(self, moves):
        """Nhãn bộ phận chưa khai map lương trong đám bút toán bị cờ.

        Soft: thiếu ``hr.payslip`` thì trả rỗng — nhãn chi tiết vẫn nằm ở
        Ghi chú trên từng bút toán. Bộ phận ĐÃ khai map sau đó thì bỏ qua
        (việc còn lại chỉ là đảo + đồng bộ lại, không phải khai).
        """
        payroll_moves = moves.filtered(
            lambda m: m.source_model == 'hr.payslip')
        if not payroll_moves or 'hr.payslip' not in self.env:
            return []
        slips = self.env['hr.payslip'].browse(
            payroll_moves.mapped('source_res_id')).exists()
        Map = self.env['vas.payroll.department.map']
        labels = []
        for slip in slips:
            dept = (
                slip.employee_id.department_id
                or slip.version_id.department_id
            )
            if dept and Map.search_count([
                ('company_id', '=', slip.company_id.id),
                ('department_id', '=', dept.id),
            ]):
                continue
            label = dept.display_name if dept else _('(không có bộ phận)')
            if label not in labels:
                labels.append(label)
        return labels

    def _check_no_pos_rounding_gap(self):
        """Chặn khóa kỳ khi quầy bật làm tròn và còn lệch chưa được phép ghi sổ."""
        if 'pos.session' not in self.env:
            return
        Sync = self.env['vas.sync']
        for period in self:
            company = period.fiscalyear_id.company_id
            sessions = self.env['pos.session'].search([
                ('company_id', '=', company.id),
                ('state', '=', 'closed'),
                ('stop_at', '>=', datetime.combine(period.date_start, time.min)),
                ('stop_at', '<=', datetime.combine(period.date_end, time.max)),
            ])
            gaps = []
            for session in sessions:
                if not Sync._pos_config_cash_rounding_on(session):
                    continue
                rounding = Sync._pos_session_rounding_gap(session)
                if float_is_zero(rounding, 2):
                    continue
                gaps.append({
                    'pos': session.config_id.display_name,
                    'session': session.display_name,
                    'amount': abs(rounding),
                })
            if gaps:
                raise UserError(
                    _('Không khóa được kỳ %s.\n\n', period.display_name)
                    + Sync._pos_rounding_error_message(gaps)
                )

    def _check_no_default_account_move(self):
        """Chốt cứng: không khóa kỳ khi còn bút toán dùng TK mặc định (theo NGÀY).

        Message gốc (đường sản phẩm) giữ NGUYÊN VĂN; khi trong đám bị cờ có
        bút toán lương thì NỐI THÊM đoạn nêu đúng tên bộ phận cần khai —
        không để kế toán bị chặn mà không biết phải khai gì.
        """
        for period in self:
            moves = period._posted_moves_in_date_range(
                [('vas_has_default_account', '=', True)],
            )
            if not moves:
                continue
            categories = self.env['vas.account.map.review']._missing_summary(
                moves[:1].company_id
            )
            message = _(
                "Không khóa được kỳ %(period)s: còn %(count)s bút toán dùng TÀI KHOẢN "
                "MẶC ĐỊNH vì sản phẩm/nhóm sản phẩm chưa khai ánh xạ.\n\n"
                "Nhóm cần khai: %(groups)s\n\n"
                "Cách xử lý: mở Connecta VAS > Bút toán, bật bộ lọc "
                "\"Dùng TK mặc định\" để xem danh sách; khai ánh xạ ở "
                "Cấu hình > Ánh xạ tài khoản > Rà soát cấu hình; đảo và đồng bộ lại "
                "các bút toán đó rồi khóa kỳ.",
                period=period.display_name,
                count=len(moves),
                groups=', '.join(categories) or _('(xem Ghi chú trên từng bút toán)'),
            )
            departments = self._unmapped_payroll_departments(moves)
            if departments:
                message += _(
                    "\n\nBộ phận cần khai map TK chi phí lương: %(depts)s — khai ở "
                    "Connecta VAS > Cấu hình > Map bộ phận lương, rồi đảo và đồng "
                    "bộ lại bút toán lương đó.",
                    depts=', '.join(departments),
                )
            else:
                # Ca "khai map muộn": move lương còn cờ nhưng mọi bộ phận đã
                # khai map sau đó → không còn gì để khai, chỉ còn đảo + sync.
                payroll_moves = moves.filtered(
                    lambda m: m.source_model == 'hr.payslip')
                if payroll_moves:
                    message += _(
                        "\n\nCó %(count)s bút toán lương dùng TK mặc định "
                        "(%(names)s) — map bộ phận đã được khai sau khi ghi sổ, "
                        "nhưng bút toán cũ chưa đồng bộ lại. Cách gỡ: đảo bút "
                        "toán lương đó rồi đồng bộ lại; bút toán mới sẽ ăn theo "
                        "map và hết cờ.",
                        count=len(payroll_moves),
                        names=', '.join(payroll_moves.mapped('name')),
                    )
            raise UserError(message)

    def _check_no_unclassified_cost_move(self):
        """Chặn khóa kỳ khi còn dòng mang khoản mục CPD (cùng khuôn TK mặc định)."""
        for period in self:
            moves = period._posted_moves_in_date_range(
                [('vas_has_unclassified_cost', '=', True)],
            )
            if not moves:
                continue
            lines = self.env['vas.move.line'].search([
                ('move_id', 'in', moves.ids),
                ('cost_item_id.code', '=', 'CPD'),
            ])
            amount = sum(abs(line.debit - line.credit) for line in lines)
            raise UserError(_(
                'Không khóa được kỳ %(period)s: còn %(line_count)s dòng bút toán '
                'mang khoản mục «Chưa phân loại» (CPD), tổng số tiền %(amount)s.\n\n'
                'Cách xử lý: mở Connecta VAS > Bút toán, bật bộ lọc '
                '«Khoản mục chưa phân loại»; khai khoản mục trên map bộ phận lương / '
                'thẻ tài sản / ánh xạ tài khoản; đảo và đồng bộ lại các bút toán '
                'đó rồi khóa kỳ.',
                period=period.display_name,
                line_count=len(lines),
                amount='{:,.0f}'.format(amount).replace(',', '.'),
            ))

    def _unvalued_stock_moves(self, period):
        """Hàng đã rời kho đi khách trong kỳ mà chưa định giá được."""
        company = period.fiscalyear_id.company_id
        moves = self.env['stock.move'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            ('location_dest_usage', '=', 'customer'),
            ('date', '>=', datetime.combine(period.date_start, time.min)),
            ('date', '<=', datetime.combine(period.date_end, time.max)),
        ])
        if not moves:
            return moves
        synced = set(self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', moves.ids),
            ('move_kind', '=', 'cogs'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ]).mapped('source_res_id'))
        Sync = self.env['vas.sync']
        return moves.filtered(
            lambda m: m.id not in synced and not Sync._cogs_amount(m)
        )

    def _check_no_unvalued_stock_move(self):
        for period in self:
            moves = self._unvalued_stock_moves(period)
            if not moves:
                continue
            products = list(dict.fromkeys(moves.mapped('product_id.display_name')))
            hien_thi = products[:5]
            if len(products) > len(hien_thi):
                hien_thi.append(_('… và %s sản phẩm khác', len(products) - len(hien_thi)))
            raise UserError(_(
                "Không khóa được kỳ %(period)s: còn %(count)s lần xuất kho đi khách "
                "CHƯA ĐỊNH GIÁ ĐƯỢC nên chưa có bút toán giá vốn nào.\n\n"
                "Bỏ qua sẽ ra lãi khống: hàng đã rời kho nhưng sổ không ghi giảm tồn "
                "kho, không ghi giá vốn.\n\n"
                "Sản phẩm: %(products)s\n"
                "Phiếu kho: %(pickings)s\n\n"
                "Nguyên nhân thường gặp: hàng FIFO/AVCO được bán trước khi có lần "
                "nhập nào và cũng chưa khai giá vốn trên thẻ sản phẩm → Odoo để giá "
                "trị = 0.\n\n"
                "Cách xử lý: mở phiếu kho ở trên, vào dòng dịch chuyển và bấm "
                "\"Điều chỉnh định giá\" để khai giá vốn thực tế (nhập kho SAU đó "
                "không tự vá lại chặng xuất đã hoàn tất), rồi chạy lại Đồng bộ VAS "
                "và khóa kỳ. Để không lặp lại: khai giá vốn trên thẻ sản phẩm trước "
                "khi bán.",
                period=period.display_name,
                count=len(moves),
                products=', '.join(hien_thi),
                pickings=', '.join(
                    dict.fromkeys(moves.mapped('picking_id.name'))
                ) or _('(không qua phiếu)'),
            ))

    def _check_no_pending_asset_lines(self):
        """HARD: không khóa kỳ khi còn lịch KH/phân bổ planned đến hạn chưa ghi."""
        Line = self.env['vas.asset.line']
        for period in self:
            pending = Line.search([
                ('period_id', '=', period.id),
                ('state', '=', 'planned'),
                ('asset_id.state', '=', 'running'),
                ('asset_id.date_start', '<=', period.date_end),
            ])
            if not pending:
                continue
            names = pending.mapped('asset_id.display_name')[:8]
            raise UserError(_(
                "Không khóa được kỳ %(period)s: còn %(count)s dòng lịch "
                "khấu hao/phân bổ CHƯA GHI (planned).\n\n"
                "Thẻ: %(assets)s\n\n"
                "Cách xử lý: chạy «Sinh khấu hao & phân bổ kỳ» (hoặc nhập "
                "sản lượng với method units), rồi khóa kỳ.",
                period=period.display_name,
                count=len(pending),
                assets=', '.join(names),
            ))

    def _check_no_pending_loan_lines(self):
        """HARD: không khóa kỳ khi còn lịch lãi vay planned đến hạn."""
        Line = self.env['vas.loan.line']
        for period in self:
            pending = Line.search([
                ('period_id', '=', period.id),
                ('state', '=', 'planned'),
                ('loan_id.state', '=', 'running'),
                ('loan_id.date_start', '<=', period.date_end),
            ])
            if not pending:
                continue
            names = pending.mapped('loan_id.display_name')[:8]
            raise UserError(_(
                "Không khóa được kỳ %(period)s: còn %(count)s dòng lịch "
                "lãi vay CHƯA GHI (planned).\n\n"
                "Thẻ vay: %(loans)s\n\n"
                "Cách xử lý: chạy «Sinh lãi vay kỳ», rồi khóa kỳ.",
                period=period.display_name,
                count=len(pending),
                loans=', '.join(names),
            ))

    def _is_fiscal_year_end_period(self):
        """Cùng tinh thần ``vas.closing.entry.is_year_end``: ngày cuối = cuối năm TC."""
        self.ensure_one()
        fy = self.fiscalyear_id
        return bool(fy and self.date_end and fy.date_to and self.date_end == fy.date_to)

    def _find_open_pl_none_balances(self):
        """TK P&L ``ending_balance_policy=none`` còn số dư YTD đến cuối kỳ.

        Trả list ``(account, amount, from_side)``.
        """
        self.ensure_one()
        company = self.fiscalyear_id.company_id
        regime = company.vas_regime_id
        if not regime:
            return []
        fy = self.fiscalyear_id
        Account = self.env['vas.account']
        Rule = self.env['vas.closing.rule']
        accounts = Account.search([
            ('regime_id', '=', regime.id),
            ('ending_balance_policy', '=', 'none'),
            ('account_type', 'in', (
                'income', 'other_income', 'expense', 'other_expense', 'equity',
            )),
        ])
        open_list = []
        for acc in accounts:
            amount, side = Rule.compute_closing_amount(
                acc, company, fy.date_from, self.date_end, 'both',
            )
            if side:
                open_list.append((acc, amount, side))
        return open_list

    def _check_no_open_pl_balance(self):
        """W10 A1=C: cuối năm chặn P&L chưa KC; giữa năm chỉ cảnh báo."""
        for period in self:
            open_list = period._find_open_pl_none_balances()
            if not open_list:
                continue
            codes = ', '.join(
                '%s (%s)' % (acc.code, '{:,.0f}'.format(amt))
                for acc, amt, _side in open_list[:20]
            )
            if len(open_list) > 20:
                codes += ', …'
            if period._is_fiscal_year_end_period():
                raise UserError(_(
                    "Không khóa được kỳ %(period)s (cuối năm tài chính): "
                    "còn tài khoản kết quả / xác định kết quả chưa kết chuyển "
                    "về hết (còn số dư).\n\n"
                    "Tài khoản còn số dư: %(accounts)s\n\n"
                    "Việc cần làm: mở Phiếu kết chuyển, lấy dữ liệu và ghi sổ "
                    "cho đến khi các tài khoản trên về 0, rồi khóa kỳ.",
                    period=period.display_name,
                    accounts=codes,
                ))
            msg = _(
                "Cảnh báo khóa kỳ %(period)s (giữa năm): còn tài khoản kết quả "
                "chưa kết chuyển hết — %(accounts)s. "
                "Kỳ giữa năm vẫn cho khóa; nên chạy phiếu kết chuyển khi cần.",
                period=period.display_name,
                accounts=codes,
            )
            _logger.warning('VAS W10: %s', msg)