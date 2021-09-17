#!/usr/bin/python
###############################################################################
# Copyleft (K) 2020-2022
# Developer: Giuseppe Checchia @eldoleo (<https://github.com/giuseppechecchia>)
###############################################################################

# Micro-docs
# ----------
#
# Remember to "pip install checkdigit requests validators cachetools" -> CTRL+C
#
# self.env['product.product'].browse(x)[0].barcode -> the barcode as is
# self.env['product.product'].browse(x)[0].is_barcode_valid -> gtin validity
#
# self.env['frmoda.barcode.checker'].regenerate_base64_imgs() -> download all
#                                                                imgs from urls
#
# first_barcodes_checking() -> a massive population to do just the first time
#
# get_barcode_data({barcode}) -> get data for a single barcode
#                                you can override the product.product write()
#                                to automatize it or use it where you want


from odoo import models, fields
import base64

import logging
import requests
import validators
import json

from cachetools import cached, TTLCache
from datetime import date
from checkdigit import gs1

from concurrent.futures import ThreadPoolExecutor
from odoo.addons.queue_job.job import job


_logger = logging.getLogger(__name__)


class BarcodeProductProduct(models.Model):

    _inherit = 'product.product'

    is_barcode_valid = fields.Boolean(
        compute="_get_barcode_validity"
    )

    def _get_barcode_validity(self):

        for item in self:
            br_obj = self.env['frmoda.barcode.checker'].search(
                [
                    ('barcode', '=', item.barcode)
                ]
            )
            item.is_barcode_valid = br_obj.formally_valid


class FrmodaBarcodeChecker(models.Model):

    _name = 'frmoda.barcode.checker'

    _description = """Barcodes validity"""

    barcode = fields.Char(
        'Barcode',
        index=True
    )

    product_id = fields.Many2one(
        string="Prodotto id",
        comodel_name='product.product',
        compute="_get_product_id"
    )

    company = fields.Char('Barcode company')
    description = fields.Char('Product description')
    image_url = fields.Char('Example Image URL')
    status = fields.Char(
        'Barcode status',
        index=True
    )
    formally_valid = fields.Boolean(
        'Barcode validity',
        index=True
    )
    image_base64 = fields.Char('Base64 Images from URL')

    # You can change it with your custom endpoint
    # assuming the {barcode} param need to be at the end
    # The results would be a dict with at least:
    # status, company, description and image_url keys
    barcode_endpoint = 'https://barcode.monster/api/'

    def get_img_as_base64(self, url):

        return base64.b64encode(requests.get(url).content)

    def doTest(self):

        breakpoint()

    def regenerate_base64_imgs(self):

        barcodes = self.search([
            ('image_base64', '=', None),
            ('image_url', '!=', None),
            ('formally_valid', '=', True),
            ('description', '!=', 'unknown'),
        ])

        for x in barcodes:

            if validators.url(x.image_url):

                image_base64 = \
                    self.get_img_as_base64(
                        x.image_url
                    )
                x.write({
                    'barcode': x.barcode,
                    'company': x.company,
                    'description': x.description,
                    'image_url': x.image_url,
                    'image_base64': image_base64,
                    'status': x.status,
                    'formally_valid': x.formally_valid
                })

    def _get_product_id(self):

        for item in self:

            x = self.search(
                [
                    ('barcode', '=', item.barcode)
                ]
            )

            item.product_id = x.id

    @job
    def _fetch_outside(self, barcode):
        self.get_barcode_data(
            barcode,
            False
        )

    def purge(self, my_string):

        my_string = my_string.replace('›  ', '')
        my_string = my_string.replace('(from barcode.monster)', '')

        return my_string.strip()

    def first_barcodes_checking(self):
        """
        Run this method to populate the model the first time
        """

        products = self.env['product.product'].search([])
        barcodes_checked = self.env['frmoda.barcode.checker'].search([])

        def _fetch_gs1(barcode):

            try:
                upc_str = barcode[0:len(barcode) - 1]
                checkdigit = gs1.calculate(upc_str)
            except Exception:
                raise Exception('Something goes wrong dude!')

            if barcode[-1] == checkdigit:
                formally_valid = True
            else:
                formally_valid = False

            return (formally_valid, barcode)

        barcodes_checked_list = list()
        barcodes = list()
        valids = list()
        invalids = list()
        append_barcode = barcodes.append
        append_valids = valids.append
        append_invalids = invalids.append
        append_checked = barcodes_checked_list.append

        for p in products:
            if p.barcode and p.barcode.isnumeric():
                append_barcode(p.barcode)

        for b in barcodes_checked:
            append_checked(b.barcode)

        # removing just processed barcodes from my set
        barcodes = set(barcodes) - set(barcodes_checked_list)

        gs1_checker_pool = ThreadPoolExecutor(max_workers=5)

        # cheking the formal validity
        for b in gs1_checker_pool.map(_fetch_gs1, barcodes):
            if b[0]:
                append_valids(b[1])
            else:
                append_invalids(b[1])

        k = 0
        for y in invalids:
            self.create({
                'barcode': y,
                'company': 'unknown',
                'description': 'unknown',
                'image_url': 'unknown',
                'status': 'not valid',
                'formally_valid': False
            })
            k += 1

        self.env.cr.commit()
        _logger.critical(f'{k} invalid barcodes signed')

        # checking valids with an outside service
        for x in valids:
            self.with_delay()._fetch_outside(x)
            # _logger.critical(f'Job opened for {x}')

    def get_barcode_data(self, barcode, check_pp=True):
        """
            get some infos about GTIN on
            differetns systems

            use this method on product.product write()
            if you have barcode on vals or something similar

            @barcode valid or invalid ean
            return void
        """
        base64 = ''
        upc_str = barcode[0:len(barcode) - 1]

        if barcode[-1] == gs1.calculate(upc_str):
            formally_valid = True
        else:
            formally_valid = False

        @cached(cache=TTLCache(maxsize=1024, ttl=600))
        def _inspect_barcode(barcode, formally_valid):

            if formally_valid:
                url = f"{self.barcode_endpoint}{barcode}"

                headers = {}
                response = requests.request(
                    "GET", url,
                    headers=headers
                )

                if response.status_code == 200:
                    ean_infos = json.loads(response.text)
                else:
                    ean_infos = {'status': 'not found'}
            else:
                ean_infos = {'status': 'not valid'}

            return ean_infos

        if check_pp:
            barcode_obj = self.search([
                ('barcode', '=', barcode)
            ])
            prod_obj = self.env['product.product'].search(
                [
                    ('barcode', '=', barcode)
                ]
            )
        else:
            barcode_obj = ''
            prod_obj = 'Silence is golden!'

        if len(barcode_obj) == 0:

            ean_infos = _inspect_barcode(barcode, formally_valid)

            if 'not' not in ean_infos['status']:
                try:
                    company = ean_infos['company']
                except Exception:
                    company = 'unknown'

                try:
                    description = ean_infos['description']
                except Exception:
                    description = 'unknown'

                try:
                    image_url = ean_infos['image_url']
                except Exception:
                    image_url = 'unknown'

                status = ean_infos['status']

            else:
                company = 'unknown'
                description = 'unknown'
                image_url = 'unknown'
                status = ean_infos['status']

            if len(prod_obj) == 0:
                raise Exception("Barcode not associated with any product")
            else:

                if image_url != 'unknown' and 'http' in image_url:
                    base64 = self.get_img_as_base64(image_url)

                self.create({
                    'barcode': barcode,
                    'company': company,
                    'description': self.purge(description),
                    'image_url': image_url,
                    'image_base64': base64,
                    'status': status,
                    'formally_valid': formally_valid
                })

        else:

            todays_date = date.today()
            current_year = todays_date.year
            current_month = todays_date.month

            # if more then 1 years has passed I refresh it
            if barcode_obj.create_date.year < current_year:
                if barcode_obj.create_date.month >= current_month:

                    ean_infos = _inspect_barcode(barcode, formally_valid)

                    if ean_infos['status'] != 'not found':
                        try:
                            company = ean_infos['company']
                        except Exception:
                            company = 'unknown'

                        try:
                            description = ean_infos['description']
                        except Exception:
                            description = 'unknown'

                        try:
                            image_url = ean_infos['image_url']
                        except Exception:
                            image_url = 'unknown'

                        status = ean_infos['status']
                    else:
                        company = 'unknown'
                        description = 'unknown'
                        image_url = 'unknown'
                        status = ean_infos['status']

                    barcode_obj.unlink()

                    if image_url != 'unknown' and 'http' in image_url:
                        base64 = self.get_img_as_base64(image_url)

                    self.create({
                        'barcode': barcode,
                        'company': company,
                        'description': self.purge(description),
                        'image_url': image_url,
                        'image_base64': base64,
                        'status': status,
                        'formally_valid': formally_valid
                    })

        self.env.cr.commit()
