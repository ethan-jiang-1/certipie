import logging

import pytest

from certipie.core import create_private_key
from tests.helpers import assert_private_key, assert_csr, assert_cert


class TestPrivateKey:
    """Tests POST /certs/private-key"""

    def test_should_return_error_when_key_size_is_not_convertible_to_int(self, client):
        r = client.post('/certs/private-key', json={'key_size': 'foo'})

        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'key_size'],
                    'msg': 'value is not a valid integer',
                    'type': 'type_error.integer'
                }
            ]
        }

    def test_should_return_error_when_key_size_is_less_than_512(self, client):
        r = client.post('/certs/private-key', json={'key_size': 40})

        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'key_size'],
                    'msg': 'ensure this value is greater than or equal to 512',
                    'type': 'value_error.number.not_ge',
                    'ctx': {'limit_value': 512}
                }
            ]
        }

    def test_should_create_pair_of_keys_without_payload(self, caplog, client, tmp_path, unzip_file):
        caplog.set_level(logging.INFO)
        r = client.post('/certs/private-key')

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_private_key(paths)
        assert len(caplog.records) == 1
        assert 'returns a zip file' in caplog.records[0].getMessage()

    @pytest.mark.parametrize(('payload', 'prefix'), [
        ({'filename_prefix': 'foo'}, 'foo'),
        ({'key_size': 1024}, 'id_rsa'),
        ({'passphrase': 'secret', 'filename_prefix': 'top_secret'}, 'top_secret')
    ])
    def test_should_create_pair_of_keys_with_payload(self, client, tmp_path, unzip_file, payload, prefix):
        r = client.post('/certs/private-key', json=payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_private_key(paths, prefix=prefix)


@pytest.fixture()
def base_payload() -> dict:
    return {
        'filename_prefix': 'my_csr',
        'country': 'FR',
        'state_or_province': 'Ile-de-France',
        'city': 'Paris',
        'organization': 'Organization Inc.',
        'common_name': 'site.com',
        'alternative_names': ['site.com', 'foo.com', '*.bar.com']
    }


class TestCommonCertificateError:
    """This class tests common validation errors for routes POST /certs/csr and POST /certs/auto-certificate."""

    @pytest.mark.parametrize('field', [
        'state_or_province',
        'city',
        'organization'
    ])
    @pytest.mark.parametrize('url_path', ['csr', 'auto-certificate'])
    def test_should_return_error_when_mandatory_field_is_empty(self, client, base_payload, field, url_path):
        base_payload[field] = ''
        r = client.post(f'/certs/{url_path}', data=base_payload)

        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', field],
                    'msg': 'field required',
                    'type': 'value_error.missing'
                }
            ]
        }

    @pytest.mark.parametrize('country', ['C', 'CAM'])
    @pytest.mark.parametrize('url_path', ['csr', 'auto-certificate'])
    def test_should_return_error_when_country_has_a_length_different_to_two(
            self, client, base_payload, country, url_path
    ):
        base_payload['country'] = country
        r = client.post(f'/certs/{url_path}', data=base_payload)

        assert r.status_code == 422
        adjective = 'least' if country == 'C' else 'most'
        error_type = 'value_error.any_str.min_length' if country == 'C' else 'value_error.any_str.max_length'
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'country'],
                    'msg': f'ensure this value has at {adjective} 2 characters',
                    'type': error_type,
                    'ctx': {'limit_value': 2}
                }
            ]
        }

    @pytest.mark.parametrize('domain', ['4', 'foo'])
    @pytest.mark.parametrize('url_path', ['csr', 'auto-certificate'])
    def test_should_return_error_when_common_name_is_not_a_domain_name(self, client, base_payload, domain, url_path):
        base_payload['common_name'] = domain
        r = client.post(f'/certs/{url_path}', data=base_payload)

        errors = [
            {
                'ctx': {'given': f'{domain}', 'permitted': ['localhost']},
                'loc': ['body', 'common_name'],
                'msg': "unexpected value; permitted: 'localhost'",
                'type': 'value_error.const'
            },
            {
                'loc': ['body', 'common_name'],
                'msg': 'not a valid domain name',
                'type': 'value_error'
            }
        ]
        if url_path == 'csr':
            del errors[0]

        assert r.status_code == 422
        assert r.json() == {'detail': errors}

    @pytest.mark.parametrize('url_path', ['csr', 'auto-certificate'])
    def test_should_return_error_when_provided_private_key_is_incorrect(
            self, tmp_path, client, base_payload, url_path
    ):
        fake_key = tmp_path / 'key.pem'
        fake_key.write_text('hello world!')

        with open(fake_key, 'rb') as f:
            r = client.post(f'/certs/{url_path}', files={'private_key': f}, data=base_payload)

        assert r.status_code == 422


class TestCsr:
    """Tests route POST /certs/csr"""

    @pytest.mark.parametrize('domain', ['4', 'foo'])
    def test_should_return_error_when_alternative_name_is_not_a_domain_name(self, client, base_payload, domain):
        base_payload['alternative_names'] = ['site.com', domain, 'foo.com']
        r = client.post('/certs/csr', data=base_payload)

        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'alternative_names', 1],
                    'msg': 'not a valid domain name',
                    'type': 'value_error'
                }
            ]
        }

    @pytest.mark.parametrize('default_filename', [True, False])
    @pytest.mark.parametrize('default_alternative_names', [True, False])
    def test_should_return_zipfile_without_giving_private_key(
            self, tmp_path, client, unzip_file, base_payload, default_filename, default_alternative_names
    ):
        if default_filename:
            csr_prefix = 'csr'
            base_payload.pop('filename_prefix')
        else:
            csr_prefix = 'my_csr'
        if default_alternative_names:
            base_payload.pop('alternative_names')

        r = client.post('/certs/csr', data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_csr(paths, csr_prefix)

    def test_should_return_zipfile_with_given_private_key_and_passphrase(
            self, tmp_path, client, private_key, unzip_file, base_payload
    ):
        with open(private_key, 'rb') as f:
            base_payload['passphrase'] = 'passphrase'
            r = client.post('/certs/csr', files={'private_key': f}, data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert len(paths) == 1
        assert_csr(paths, 'my_csr')

    def test_should_return_zipfile_with_given_private_key_and_no_passphrase(
            self, caplog, tmp_path, client, unzip_file, base_payload
    ):
        caplog.set_level(logging.INFO)
        key = tmp_path / 'key.pem'
        create_private_key(f'{key}')

        with key.open('rb') as f:
            r = client.post('/certs/csr', files={'private_key': f}, data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert len(paths) == 1
        assert_csr(paths, 'my_csr')
        assert len(caplog.records) == 1
        assert 'returns a zip file' in caplog.records[0].getMessage()


class TestAutoCertificate:
    """Tests route POST /certs/auto-certificate"""

    @pytest.mark.parametrize('domain', ['4', 'foo'])
    def test_should_return_error_when_alternative_name_is_not_a_domain_name(self, client, base_payload, domain):
        base_payload['alternative_names'] = ['site.com', domain, 'foo.com']
        r = client.post('/certs/auto-certificate', data=base_payload)

        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {'loc': ['body', 'alternative_names', 1], 'msg': 'not a valid domain name', 'type': 'value_error'},
                {'loc': ['body', 'alternative_names', 1], 'msg': 'value is not a valid IPv4 address',
                 'type': 'value_error.ipv4address'},
                {'loc': ['body', 'alternative_names', 1], 'msg': 'value is not a valid IPv6 address',
                 'type': 'value_error.ipv6address'},
                {'loc': ['body', 'alternative_names', 1], 'msg': 'value is not a valid IPv4 network',
                 'type': 'value_error.ipv4network'},
                {'loc': ['body', 'alternative_names', 1], 'msg': 'value is not a valid IPv6 network',
                 'type': 'value_error.ipv6network'},
                {'loc': ['body', 'alternative_names', 1], 'msg': "unexpected value; permitted: 'localhost'",
                 'type': 'value_error.const', 'ctx': {'given': f'{domain}', 'permitted': ['localhost']}}
            ]
        }

    @pytest.mark.parametrize('value', [-1, 'foo'])
    def test_should_return_error_when_end_validity_is_not_a_valid_integer(self, client, base_payload, value):
        base_payload['end_validity'] = value
        r = client.post('/certs/auto-certificate', data=base_payload)

        assert r.status_code == 422

        detail = r.json()['detail']
        assert len(detail) == 1
        assert detail[0]['loc'] == ['body', 'end_validity']

    @pytest.mark.parametrize('common_name', ['localhost', 'site.com'])
    def test_should_return_zipfile_without_given_filename_prefix(
            self, tmp_path, client, unzip_file, base_payload, common_name
    ):
        base_payload.pop('filename_prefix')
        base_payload['common_name'] = common_name
        r = client.post('/certs/auto-certificate', data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_cert(paths)

    def test_should_return_zipfile_without_given_alternative_names(self, tmp_path, client, unzip_file, base_payload):
        base_payload.pop('alternative_names')
        base_payload['filename_prefix'] = 'cert'
        r = client.post('/certs/auto-certificate', data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_cert(paths)

    def test_should_return_zipfile_with_given_private_key_and_passphrase(
            self, tmp_path, client, private_key, unzip_file, base_payload
    ):
        base_payload['filename_prefix'] = 'cert'
        with open(private_key, 'rb') as f:
            base_payload['passphrase'] = 'passphrase'
            r = client.post('/certs/auto-certificate', files={'private_key': f}, data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_cert(paths)

    def test_should_return_zipfile_with_given_private_key_and_no_passphrase(
            self, caplog, tmp_path, client, unzip_file, base_payload
    ):
        caplog.set_level(logging.INFO)
        key = tmp_path / 'key.pem'
        create_private_key(f'{key}')
        base_payload['filename_prefix'] = 'certificate'

        with key.open('rb') as f:
            r = client.post('/certs/auto-certificate', files={'private_key': f}, data=base_payload)

        assert r.status_code == 200
        assert r.headers['content-type'] == 'application/zip'

        paths = unzip_file(r.content, tmp_path)
        assert_cert(paths, 'certificate')
        assert len(caplog.records) == 1
        assert 'returns a zip file' in caplog.records[0].getMessage()
