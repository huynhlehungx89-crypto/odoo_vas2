# -*- coding: utf-8 -*-
"""POS adapter — đọc pos.order / pos.session, ghi vas.move. Soft depend."""
from odoo import Command, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

class VasSyncPos(models.AbstractModel):
    _inherit = 'vas.sync'

    def _sync_pos(self, company, date_from=None, date_to=None):
        """Bán/trả tại quầy + kết ca. Im lặng nếu không có pos.order."""
        stats = {
            'orders': {'created': 0, 'skipped': 0},
            'cogs': {'created': 0, 'skipped': 0},
            'sessions': {'created': 0, 'skipped': 0},
            'cash_in_out': {'created': 0, 'skipped': 0},
        }
        if not self._pos_available():
            return stats
        Order = self.env['pos.order']
        Session = self.env['pos.session']
        order_domain = [
            ('company_id', '=', company.id),
            ('state', 'in', ('paid', 'done')),
        ]
        if date_from:
            order_domain.append(('date_order', '>=', fields.Datetime.to_datetime(date_from)))
        if date_to:
            order_domain.append((
                'date_order', '<=',
                fields.Datetime.to_datetime(date_to).replace(hour=23, minute=59, second=59),
            ))
        cutoff = company.vas_start_date
        for order in Order.search(order_domain, order='date_order, id'):
            day = fields.Date.to_date(order.date_order)
            if cutoff and day < cutoff:
                stats['orders']['skipped'] += 1
                continue
            sale = self._sync_one_pos_order(order, company)
            if sale:
                stats['orders']['created'] += 1
            else:
                stats['orders']['skipped'] += 1
            cogs = self._sync_one_pos_cogs(order, company)
            if cogs:
                stats['cogs']['created'] += 1
            else:
                stats['cogs']['skipped'] += 1

        session_domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'closed'),
        ]
        if date_from:
            session_domain.append(('stop_at', '>=', fields.Datetime.to_datetime(date_from)))
        if date_to:
            session_domain.append((
                'stop_at', '<=',
                fields.Datetime.to_datetime(date_to).replace(hour=23, minute=59, second=59),
            ))
        rounding_gaps = []
        for session in Session.search(session_domain, order='stop_at, id'):
            day = self._source_date(session)
            if cutoff and day < cutoff:
                stats['sessions']['skipped'] += 1
                continue
            created, io_created, gaps = self._sync_one_pos_session(session, company)
            stats['sessions']['created'] += created
            stats['sessions']['skipped'] += 0 if created else 1
            stats['cash_in_out']['created'] += io_created
            rounding_gaps.extend(gaps)
        if rounding_gaps:
            raise UserError(self._pos_rounding_error_message(rounding_gaps))
        return stats

    def _pos_order_is_refund(self, order):
        if getattr(order, 'is_refund', False):
            return True
        if float_compare(order.amount_total or 0.0, 0.0, 2) < 0:
            return True
        if any(float_compare(l.qty or 0.0, 0.0, 2) < 0 for l in order.lines):
            return True
        return False

    def _sync_one_pos_order(self, order, company):
        refund = self._pos_order_is_refund(order)
        move_kind = 'pos_refund' if refund else 'pos_sale'
        if self._already_synced(order._name, order.id, move_kind):
            return self.env['vas.move']
        regime = company.vas_regime_id
        if not regime:
            return self.env['vas.move']
        total = abs(order.amount_total or 0.0)
        tax_amt = abs(order.amount_tax or 0.0)
        untaxed = float_round(total - tax_amt, precision_digits=2)
        if float_is_zero(total, precision_digits=2) and float_is_zero(untaxed, 2):
            return self.env['vas.move']

        acc_131 = self._account_by_code(regime, '131')
        acc_33311 = self._account_by_code(regime, '33311')
        fallbacks = []
        event = 'pos_refund' if refund else 'pos_sale'
        partner = order.partner_id
        session_vals = self._pos_session_line_vals(order)
        date = self._source_date(order)
        cmds = []
        seq = 10

        def _line(account, debit, credit, name, tax=None, status='none'):
            nonlocal seq
            vals = {
                'sequence': seq,
                'account_id': account.id,
                'name': name,
                'debit': debit,
                'credit': credit,
                'currency_id': company.currency_id.id,
                'partner_id': partner.id if partner else False,
                'tax_status': status,
                **session_vals,
            }
            if tax:
                vals['tax_id'] = tax.id
            cmds.append(Command.create(vals))
            seq += 10

        if refund:
            # Ngược chiều bán: Nợ 511 + 33311 / Có 131
            for account, part, _cost in self._product_amount_splits(
                order, 'product_revenue', 'untaxed', company, untaxed, fallbacks,
                event_type=event,
            ):
                _line(account, part, 0.0, _('Trả hàng quầy %s') % order.display_name)
            tax_rec, status = self._pos_order_tax(order, company, date)
            if not float_is_zero(tax_amt, 2):
                _line(
                    acc_33311, tax_amt, 0.0,
                    _('Thuế GTGT trả hàng quầy %s') % order.display_name,
                    tax=tax_rec, status=status,
                )
            _line(acc_131, 0.0, total, _('Phải thu trả hàng quầy %s') % order.display_name)
        else:
            _line(acc_131, total, 0.0, _('Bán quầy %s') % order.display_name)
            for account, part, _cost in self._product_amount_splits(
                order, 'product_revenue', 'untaxed', company, untaxed, fallbacks,
                event_type=event,
            ):
                _line(account, 0.0, part, _('Doanh thu quầy %s') % order.display_name)
            tax_rec, status = self._pos_order_tax(order, company, date)
            if not float_is_zero(tax_amt, 2):
                _line(
                    acc_33311, 0.0, tax_amt,
                    _('Thuế GTGT quầy %s') % order.display_name,
                    tax=tax_rec, status=status,
                )

        debit_sum = sum(c[2]['debit'] for c in cmds)
        credit_sum = sum(c[2]['credit'] for c in cmds)
        gap = float_round(debit_sum - credit_sum, precision_digits=2)
        if not float_is_zero(gap, 2):
            session = order.session_id
            info = {
                'pos': session.config_id.display_name if session else _('(không rõ quầy)'),
                'session': session.display_name if session else _('(không rõ phiên)'),
                'amount': abs(gap),
            }
            if session and self._pos_config_cash_rounding_on(session):
                raise UserError(self._pos_rounding_error_message([info]))
            raise UserError(_(
                'Đơn quầy «%(order)s» phiên «%(session)s» lệch Nợ/Có %(amount)s. '
                'VAS không dồn khoản lệch vào doanh thu 511.',
                order=order.display_name,
                session=info['session'],
                amount=self._pos_format_amount(info['amount']),
            ))

        journal = self._resolve_journal(event, order, company)
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': move_kind,
            'ref': _('Trả hàng tại quầy %s') % order.display_name if refund
            else _('Bán tại quầy %s') % order.display_name,
            'source_model': order._name,
            'source_res_id': order.id,
            'source_ref': order.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': cmds,
            **self._default_account_flag_vals(fallbacks),
        })
        return self._post_or_flag_period_missing(move)

    def _pos_order_tax(self, order, company, date):
        Tax = self.env['vas.tax']
        odoo_taxes = order.lines.mapped('tax_ids')
        tax, status, _warn = Tax.find_for_invoice_line(
            company, date, 'output',
            odoo_taxes=odoo_taxes,
            empty_taxes=not odoo_taxes,
        )
        return tax, status or 'none'

    def _pos_order_stock_moves(self, order):
        pickings = order.picking_ids
        moves = pickings.mapped('move_ids').filtered(lambda m: m.state == 'done')
        if not moves and 'stock_reference_ids' in order._fields:
            refs = order.stock_reference_ids
            if refs and 'move_ids' in refs._fields:
                moves = refs.mapped('move_ids').filtered(lambda m: m.state == 'done')
        return moves

    def _sync_one_pos_cogs(self, order, company):
        if self._already_synced(order._name, order.id, 'pos_cogs'):
            return self.env['vas.move']
        stock_moves = self._pos_order_stock_moves(order)
        if not stock_moves:
            return self.env['vas.move']
        amount = 0.0
        date = False
        fallbacks = []
        notes = []
        weights = []
        refund = self._pos_order_is_refund(order)
        for sm in stock_moves:
            if refund:
                val = abs(self._pos_refund_origin_cogs_amount(
                    order, sm, fallbacks, notes,
                ) or 0.0)
            else:
                val = abs(self._cogs_amount(sm) or 0.0)
            if float_is_zero(val, 2) and not refund:
                continue
            amount += val
            sm_date = self._source_date(sm)
            if not date or sm_date > date:
                date = sm_date
            weight = val if not float_is_zero(val, 2) else (
                self._stock_move_qty(sm) or 1.0
            )
            weights.append((sm.product_id, weight))
        if float_is_zero(amount, 2) and not refund:
            return self.env['vas.move']
        if not weights:
            return self.env['vas.move']
        date = date or self._source_date(order)
        # Tạo recordset giả để chia TK: dùng order + _product_amount_splits
        # trên pos.order theo giá vốn từng SP (weights).
        regime = company.vas_regime_id
        partner = order.partner_id
        session_vals = self._pos_session_line_vals(order)
        cmds = []
        seq = 10
        buckets = {}
        total_w = 0.0
        for product, weight in weights:
            acc_cogs = self._product_account(product, 'product_cogs', company, fallbacks)
            acc_inv = self._product_account(product, 'product_inventory', company, fallbacks)
            key = (acc_cogs.id, acc_inv.id)
            bucket = buckets.setdefault(key, [acc_cogs, acc_inv, 0.0])
            bucket[2] += weight
            total_w += weight
        allocated = 0.0
        items = list(buckets.values())
        name = _('Giá vốn quầy %s') % order.display_name

        def _mk(account, debit, credit):
            nonlocal seq
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': account.id,
                'name': name,
                'debit': debit,
                'credit': credit,
                'currency_id': company.currency_id.id,
                'partner_id': partner.id if partner else False,
                'tax_status': 'none',
                **session_vals,
            }))
            seq += 10

        for i, (acc_cogs, acc_inv, weight) in enumerate(items):
            part = (
                float_round(amount - allocated, 2)
                if i == len(items) - 1
                else float_round(amount * weight / total_w, 2)
            )
            allocated = float_round(allocated + part, 2)
            if refund:
                _mk(acc_inv, part, 0.0)
                _mk(acc_cogs, 0.0, part)
            else:
                _mk(acc_cogs, part, 0.0)
                _mk(acc_inv, 0.0, part)

        journal = self._resolve_journal('pos_cogs', order, company)
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'pos_cogs',
            'ref': name,
            'source_model': order._name,
            'source_res_id': order.id,
            'source_ref': order.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': cmds,
            **self._merge_move_flag_vals(
                self._default_account_flag_vals(fallbacks),
                {'narration': '\n'.join(notes)} if notes else {},
            ),
        })
        return self._post_or_flag_period_missing(move)

    def _pos_cash_account(self, company):
        if company.vas_pos_cash_account_id:
            return company.vas_pos_cash_account_id
        return self._account_by_code(company.vas_regime_id, '1111')

    def _pos_payment_type(self, payment):
        method = payment.payment_method_id
        ptype = getattr(method, 'type', False) or ''
        if ptype:
            return ptype
        if getattr(method, 'is_cash_count', False):
            return 'cash'
        journal = method.journal_id
        if journal and journal.type == 'cash':
            return 'cash'
        if journal and journal.type == 'bank':
            return 'bank'
        return 'other'

    def _sync_one_pos_session(self, session, company):
        created = 0
        io_created = self._sync_pos_cash_in_out(session, company)
        regime = company.vas_regime_id
        date = self._source_date(session)
        session_vals = self._pos_session_line_vals(session)
        acc_131 = self._account_by_code(regime, '131')
        acc_112 = self._account_by_code(regime, '112')
        acc_111 = self._pos_cash_account(company)
        acc_1381 = self._account_by_code(regime, '1381')
        acc_3381 = self._account_by_code(regime, '3381')

        cash_amt = bank_amt = pay_later = 0.0
        for pay in session.order_ids.mapped('payment_ids'):
            amt = pay.amount or 0.0
            ptype = self._pos_payment_type(pay)
            if ptype == 'cash':
                cash_amt += amt
            elif ptype == 'pay_later':
                pay_later += amt
            else:
                bank_amt += amt
        cash_amt = float_round(cash_amt, 2)
        bank_amt = float_round(bank_amt, 2)

        diff = float_round(session.cash_register_difference or 0.0, 2)
        shortage = abs(diff) if float_compare(diff, 0.0, 2) < 0 else 0.0
        overage = diff if float_compare(diff, 0.0, 2) > 0 else 0.0
        cash_to_111 = float_round(cash_amt + min(diff, 0.0), 2)

        if (
            not self._already_synced(session._name, session.id, 'pos_session_cash')
            and not float_is_zero(cash_to_111, 2)
        ):
            move = self._pos_post_pair(
                company, date, session, 'pos_session_cash', 'pos_session_cash',
                _('Kết ca tiền mặt %s') % session.display_name,
                acc_111, cash_to_111, acc_131, cash_to_111, session_vals,
            )
            if move:
                created += 1
        elif self._already_synced(session._name, session.id, 'pos_session_cash'):
            pass

        if (
            not self._already_synced(session._name, session.id, 'pos_session_bank')
            and not float_is_zero(bank_amt, 2)
        ):
            move = self._pos_post_pair(
                company, date, session, 'pos_session_bank', 'pos_session_bank',
                _('Kết ca thẻ/ví %s') % session.display_name,
                acc_112, bank_amt, acc_131, bank_amt, session_vals,
            )
            if move:
                created += 1

        if not self._already_synced(session._name, session.id, 'pos_cash_diff'):
            if not float_is_zero(shortage, 2):
                move = self._pos_post_pair(
                    company, date, session, 'pos_cash_diff', 'pos_cash_shortage',
                    _('Đếm thiếu két %s') % session.display_name,
                    acc_1381, shortage, acc_131, shortage, session_vals,
                )
                if move:
                    created += 1
            elif not float_is_zero(overage, 2):
                move = self._pos_post_pair(
                    company, date, session, 'pos_cash_diff', 'pos_cash_overage',
                    _('Đếm thừa két %s') % session.display_name,
                    acc_131, overage, acc_3381, overage, session_vals,
                )
                if move:
                    created += 1

        gaps = []
        rounding = self._pos_session_rounding_gap(session)
        if (
            self._pos_config_cash_rounding_on(session)
            and not float_is_zero(rounding, 2)
        ):
            gaps.append({
                'pos': session.config_id.display_name,
                'session': session.display_name,
                'amount': abs(rounding),
            })
        return created, io_created, gaps

    def _pos_config_cash_rounding_on(self, session):
        return bool(getattr(session.config_id, 'cash_rounding', False))

    def _pos_mid_session_cash_lines(self, session):
        """Rút/bỏ tiền giữa ca — loại dòng sao kê kết ca (gom tiền mặt / lệch đếm)."""
        if 'statement_line_ids' not in session._fields:
            return self.env['account.bank.statement.line']
        lines = session.sudo().statement_line_ids
        if 'pos_order_id' in lines._fields:
            lines = lines.filtered(lambda l: not l.pos_order_id)
        return lines.filtered(
            lambda l: (
                not float_is_zero(l.amount or 0.0, 2)
                and self._pos_statement_is_cash_io(l, session)
            )
        )

    def _pos_statement_is_cash_io(self, line, session):
        ref = (line.payment_ref or line.name or '')
        low = ref.lower()
        if low == (session.name or '').lower():
            return False
        if 'cash difference' in low:
            return False
        if ref.startswith('%s-' % session.name):
            return True
        return any(tok in low for tok in (
            'cash in', 'cash out', 'cash-in', 'cash-out',
        ))

    def _pos_session_io_net(self, session):
        return float_round(
            sum(self._pos_mid_session_cash_lines(session).mapped('amount')), 2,
        )

    def _pos_session_rounding_gap(self, session):
        """Lệch 131 còn lại sau kết ca và rút/bỏ giữa ca — không ghi vào 511."""
        cash_amt = bank_amt = pay_later = 0.0
        for pay in session.order_ids.mapped('payment_ids'):
            amt = pay.amount or 0.0
            ptype = self._pos_payment_type(pay)
            if ptype == 'cash':
                cash_amt += amt
            elif ptype == 'pay_later':
                pay_later += amt
            else:
                bank_amt += amt
        cash_amt = float_round(cash_amt, 2)
        bank_amt = float_round(bank_amt, 2)
        diff = float_round(session.cash_register_difference or 0.0, 2)
        shortage = abs(diff) if float_compare(diff, 0.0, 2) < 0 else 0.0
        overage = diff if float_compare(diff, 0.0, 2) > 0 else 0.0
        cash_to_111 = float_round(cash_amt + min(diff, 0.0), 2)
        booked_131 = float_round(sum(
            (o.amount_total or 0.0)
            for o in session.order_ids.filtered(lambda o: o.state in ('paid', 'done'))
        ), 2)
        to_clear = float_round(booked_131 - pay_later, 2)
        cleared = float_round(cash_to_111 + bank_amt + shortage - overage, 2)
        io_net = self._pos_session_io_net(session)
        return float_round(to_clear - cleared + io_net, 2)

    def _pos_format_amount(self, amount):
        return '{:,.0f}'.format(abs(amount or 0.0)).replace(',', '.')

    def _pos_rounding_error_message(self, gaps):
        rows = []
        for gap in gaps:
            rows.append(_(
                'Quầy «%(pos)s», phiên «%(session)s», số tiền lệch %(amount)s.',
                pos=gap['pos'],
                session=gap['session'],
                amount=self._pos_format_amount(gap['amount']),
            ))
        return _(
            'Quầy có bật làm tròn tiền và phát sinh lệch. VAS không ghi khoản '
            'lệch vào doanh thu 511 (doanh thu trên sổ phải khớp hóa đơn đã xuất; '
            'doanh nghiệp không dùng nghiệp vụ làm tròn).\n\n%s\n\n'
            'Tắt làm tròn trên quầy rồi đồng bộ lại. Kỳ có chứng từ này '
            'không khóa được cho đến khi hết lệch.',
            '\n'.join(rows),
        )

    def _sync_pos_cash_in_out(self, session, company):
        """Rút/bỏ tiền giữa ca: bút toán riêng, đối ứng = TK quỹ nộp tiền quầy.

        Tái dùng ``vas_pos_cash_account_id`` (cùng TK Nợ kết ca / mặc định 1111):
        tiền rời két về quỹ hoặc bỏ thêm từ quỹ — không đoán TK khác. Trống
        → vẫn ghi 1111 + cờ mặc định + chặn khóa kỳ.
        """
        created = 0
        acc_111 = self._pos_cash_account(company)
        acc_131 = self._account_by_code(company.vas_regime_id, '131')
        session_vals = self._pos_session_line_vals(session)
        configured = bool(company.vas_pos_cash_account_id)
        for line in self._pos_mid_session_cash_lines(session):
            if self._already_synced(line._name, line.id, 'pos_cash_io'):
                continue
            amt = float_round(line.amount or 0.0, 2)
            abs_amt = abs(amt)
            date = fields.Date.to_date(line.date)
            fallbacks = []
            if not configured:
                fallbacks.append({
                    'label': _(
                        'Phiên %(session)s — rút/bỏ tiền giữa ca %(amount)s: '
                        'chưa khai TK quỹ nộp tiền quầy, dùng mặc định 1111',
                        session=session.display_name,
                        amount=self._pos_format_amount(abs_amt),
                    ),
                })
            if float_compare(amt, 0.0, 2) < 0:
                ref = _('Rút tiền giữa ca %s') % session.display_name
                debit_acc, credit_acc = acc_111, acc_131
            else:
                ref = _('Bỏ thêm tiền giữa ca %s') % session.display_name
                debit_acc, credit_acc = acc_131, acc_111
            move = self._pos_post_pair(
                company, date, line, 'pos_cash_io', 'pos_session_cash',
                ref, debit_acc, abs_amt, credit_acc, abs_amt, session_vals,
                fallbacks=fallbacks,
            )
            if move:
                created += 1
        return created

    def _pos_post_pair(
        self, company, date, source, move_kind, event_type, ref,
        debit_acc, debit_amt, credit_acc, credit_amt, session_vals,
        fallbacks=None,
    ):
        if not debit_acc or not credit_acc:
            raise ValueError('POS pair missing account')
        journal = self._resolve_journal(event_type, source, company)
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': journal.id,
            'regime_id': company.vas_regime_id.id,
            'move_kind': move_kind,
            'ref': ref,
            'source_model': source._name,
            'source_res_id': source.id,
            'source_ref': source.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            **self._default_account_flag_vals(fallbacks or []),
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': debit_acc.id,
                    'name': ref,
                    'debit': debit_amt,
                    'credit': 0.0,
                    'currency_id': company.currency_id.id,
                    'tax_status': 'none',
                    **session_vals,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': credit_acc.id,
                    'name': ref,
                    'debit': 0.0,
                    'credit': credit_amt,
                    'currency_id': company.currency_id.id,
                    'tax_status': 'none',
                    **session_vals,
                }),
            ],
        })
        return self._post_or_flag_period_missing(move)
