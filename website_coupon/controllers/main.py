# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil import parser
from odoo import http
from odoo.http import request


class WebsiteCoupon(http.Controller):

    @http.route(['/shop/cart'], type='http', auth="public", website=True)
    def cart(self, **post):
        """ This function is overwritten because we need to pass the value
        'coupon_not_available' to the template, in order to show the error
        message to the user that, 'this coupon is not available'.
        """

        order = request.website.sale_get_order()
        if order:
            from_currency = order.company_id.currency_id
            to_currency = order.pricelist_id.currency_id
            compute_currency = lambda price: from_currency.compute(  # noqa
                price, to_currency)
        else:
            compute_currency = lambda price: price  # noqa

        values = {
            'website_sale_order': order,
            'compute_currency': compute_currency,
            'suggested_products': [],
        }
        if order:
            _order = order
            if not request.env.context.get('pricelist'):
                _order = order.with_context(pricelist=order.pricelist_id.id)
            values['suggested_products'] = _order._cart_accessories()

        if post.get('type') == 'popover':
            # force no-cache so IE11 doesn't cache this XHR
            return request.render("website_sale.cart_popover", values,
                                  headers={'Cache-Control': 'no-cache'})

        if post.get('code_not_available'):
            values['code_not_available'] = post.get('code_not_available')
        elif post.get('coupon_not_available'):
            values['coupon_not_available'] = post.get('coupon_not_available')
        return request.render("website_sale.cart", values)

    @http.route(['/shop/gift_coupon'],
                type='http', auth="public", website=True)
    def gift_coupon(self, promo_voucher, **post):
        """ This function will be executed when we click the apply button of
        the voucher code in the website. It will verify the validity and
        availability of that coupon. If it can be applied, the coupon will be
        applied and coupon balance will also be updated.
        """

        curr_user = request.env.user
        coupon = request.env['gift.coupon'].sudo().search(
            [('code', '=', promo_voucher)], limit=1)
        flag = True
        if coupon and coupon.total_avail > 0:
            applied_coupons = request.env['partner.coupon'].sudo().search(
                [('coupon', '=', promo_voucher),
                 ('partner_id', '=', curr_user.partner_id.id)],
                limit=1)

            # checking voucher date and limit for each user for this coupon
            if coupon.partner_id:
                if curr_user.partner_id.id != coupon.partner_id.id:
                    flag = False
            today = datetime.now().date()
            voucher_expiry = parser.parse(coupon.voucher.expiry_date).date()
            if (flag
                    and applied_coupons.number < coupon.limit
                    and today <= voucher_expiry):
                # checking coupon validity
                #    checking date of coupon
                if coupon.start_date and coupon.end_date:
                    if (today < parser.parse(coupon.start_date).date()
                            or today > parser.parse(coupon.end_date).date()):
                        flag = False
                elif coupon.start_date:
                    if today < parser.parse(coupon.start_date).date():
                        flag = False
                elif coupon.end_date:
                    if today > parser.parse(coupon.end_date).date():
                        flag = False
            else:
                flag = False
        else:
            flag = False
        if flag:
            voucher_type = coupon.voucher.voucher_type
            voucher_val = coupon.voucher_val
            type = coupon.type
            coupon_product = request.env['product.product'].sudo().search(
                [('name', '=', 'Gift Coupon')], limit=1)
            if coupon_product:
                order = request.website.sale_get_order(force_create=1)
                flag_product = False
                for line in order.order_line:
                    if line.product_id.name == 'Gift Coupon':
                        flag = False
                        break
                if flag and order.order_line:
                    if voucher_type == 'product':
                        # the voucher type is product
                        product_id = coupon.voucher.product_id
                        for line in order.order_line:
                            if line.product_id.name == product_id.name:
                                    flag_product = True
                    elif voucher_type == 'category':
                        # the voucher type is category
                        voucher_cat = coupon.voucher.product_categ
                        for ol in order.order_line:
                            if ol.product_id.categ_id.name == voucher_cat.name:
                                flag_product = True
                    elif voucher_type == 'all':
                        # the voucher is applicable to all products
                        flag_product = True
                    if flag_product:
                        # the voucher is applicable
                        if type == 'fixed':
                            # coupon type is 'fixed'
                            if voucher_val < order.amount_total:
                                coupon_product.product_tmpl_id.write(
                                    {'list_price': -voucher_val})

                            else:
                                return request.redirect(
                                    "/shop/cart?coupon_not_available=3")
                        elif type == 'percentage':
                            # coupon type is percentage
                            amount_final = 0
                            factor = (voucher_val / 100)
                            if voucher_type == 'product':
                                for ol in order.order_line:
                                    if ol.product_id.name == product_id.name:
                                        amount_final = factor * ol.price_total
                                        break
                            elif voucher_type == 'category':
                                for ol in order.order_line:
                                    cat_name = ol.product_id.categ_id.name
                                    if cat_name == voucher_cat.name:
                                        amount_final += factor * ol.price_total
                            elif voucher_type == 'all':
                                amount_final = factor * order.amount_total
                            coupon_product.product_tmpl_id.write(
                                {'list_price': -amount_final})
                        order._cart_update(product_id=coupon_product.id,
                                           set_qty=1, add_qty=1)
                        # updating coupon balance
                        total = coupon.total_avail - 1
                        coupon.write({'total_avail': total})
                        # creating a record for this partner,
                        # i.e he is used this coupon once
                        if not applied_coupons:
                            curr_user.partner_id.write({
                                'applied_coupon': [(0, 0, {
                                    'partner_id': curr_user.partner_id.id,
                                    'coupon': coupon.code,
                                    'number': 1,
                                    })]
                                })
                        else:
                            applied_coupons.write(
                                {'number': applied_coupons.number + 1})
                    else:
                        return request.redirect(
                            "/shop/cart?coupon_not_available=1")
                else:
                    return request.redirect(
                        "/shop/cart?coupon_not_available=2")
        else:
            return request.redirect("/shop/cart?coupon_not_available=1")

        return request.redirect("/shop/cart")
