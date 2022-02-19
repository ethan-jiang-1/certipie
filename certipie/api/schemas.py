from typing import Optional

from pydantic import BaseModel, Field, SecretBytes

from certipie.core import is_domain_name


class PrivateKeyInput(BaseModel):
    filename_prefix: Optional[str] = Field(
        'id_rsa',
        description=(
            'The prefix if the files created. For example if you pass "id_rsa", you will have a zip with two files'
            '"id_rsa.pem" for the private key and "id_rsa.pub" for the public key.'
        ),
        example='id_rsa'
    )
    key_size: Optional[int] = Field(
        2048, description='Like te name said.. the key size for the private key.', ge=512, example=2048
    )
    passphrase: Optional[SecretBytes] = Field(
        b'', description='Passphrase used to encrypt the private_key, can be optional.', example='my passphrase'
    )


class DomainName(str):
    @classmethod
    def validate(cls, value):
        if not is_domain_name(value):
            raise ValueError('not a valid domain name')

        return value

    @classmethod
    def __get_validators__(cls):
        yield cls.validate
