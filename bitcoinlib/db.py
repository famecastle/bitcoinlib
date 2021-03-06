# -*- coding: utf-8 -*-
#
#    BitcoinLib - Python Cryptocurrency Library
#    DataBase - SqlAlchemy database definitions
#    © 2016 - 2017 September - 1200 Web Development <http://1200wd.com/>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

try:
    import enum
except ImportError:
    import enum34 as enum
import datetime
from sqlalchemy import create_engine
from sqlalchemy import (Column, Integer, BigInteger, UniqueConstraint, CheckConstraint, String, Boolean, Sequence,
                        ForeignKey, DateTime, Numeric, Text)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
from bitcoinlib.main import *

_logger = logging.getLogger(__name__)
_logger.info("Using Database %s" % DEFAULT_DATABASE)
Base = declarative_base()


class DbInit:
    """
    Initialize database and open session

    Import data if database did not exist yet

    """
    def __init__(self, db_uri=None):
        if db_uri is None:
            db_uri = os.path.join(BCL_DATABASE_DIR, DEFAULT_DATABASE)
        o = urlparse(db_uri)
        if not o.scheme:
            db_uri = 'sqlite:///%s' % db_uri
        if db_uri.startswith("sqlite://") and ALLOW_DATABASE_THREADS:
            if "?" in db_uri: db_uri += "&"
            else: db_uri += "?"
            db_uri += "check_same_thread=False"
        self.engine = create_engine(db_uri, isolation_level='READ UNCOMMITTED')
        Session = sessionmaker(bind=self.engine)

        Base.metadata.create_all(self.engine)
        self._import_config_data(Session)

        self.session = Session()

        # VERIFY AND UPDATE DATABASE
        # Just a very simple database update script, without any external libraries for now
        #
        try:
            version_db = self.session.query(DbConfig.value).filter_by(variable='version').scalar()
            if BITCOINLIB_VERSION != version_db:
                _logger.warning("BitcoinLib database (%s) is from different version then library code (%s). "
                                "Let's try to update database." % (version_db, BITCOINLIB_VERSION))

                if version_db == '0.4.10' and BITCOINLIB_VERSION == '0.4.11':
                    column = Column('latest_txid', String(32))
                    add_column(self.engine, 'keys', column)
                    _logger.info("Updated BitcoinLib database from version 0.4.10 to 0.4.11")
                    self.session.query(DbConfig).filter(DbConfig.variable == 'version').update(
                        {DbConfig.value: BITCOINLIB_VERSION})
                    self.session.commit()
        except Exception as e:
            _logger.warning("Error when verifying version or updating database: %s" % e)

    @staticmethod
    def _import_config_data(ses):
        session = ses()
        session.merge(DbConfig(variable='version', value=BITCOINLIB_VERSION))
        session.merge(DbConfig(variable='installation_date', value=str(datetime.datetime.now())))
        url = ''
        try:
            url = str(session.bind.url)
        except:
            pass
        session.merge(DbConfig(variable='installation_url', value=url))
        session.commit()
        session.close()


def add_column(engine, table_name, column):
    column_name = column.compile(dialect=engine.dialect)
    column_type = column.type.compile(engine.dialect)
    engine.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table_name, column_name, column_type))


class DbConfig(Base):
    """
    BitcoinLib configuration variables

    """
    __tablename__ = 'config'
    variable = Column(String(30), primary_key=True)
    value = Column(String(255))


class DbWallet(Base):
    """
    Database definitions for wallets in Sqlalchemy format

    Contains one or more keys.

    """
    __tablename__ = 'wallets'
    id = Column(Integer, Sequence('wallet_id_seq'), primary_key=True)
    name = Column(String(80), unique=True)
    owner = Column(String(50))
    network_name = Column(String(20), ForeignKey('networks.name'))
    network = relationship("DbNetwork")
    purpose = Column(Integer)
    scheme = Column(String(25))
    witness_type = Column(String(20), default='legacy')
    encoding = Column(String(15), default='base58', doc="Default encoding to use for address generation")
    main_key_id = Column(Integer)
    keys = relationship("DbKey", back_populates="wallet")
    transactions = relationship("DbTransaction", back_populates="wallet")
    # balance = Column(Integer, default=0)
    multisig_n_required = Column(Integer, default=1, doc="Number of required signature for multisig, "
                                                         "only used for multisignature master key")
    sort_keys = Column(Boolean, default=False, doc="Sort keys in multisig wallet")
    parent_id = Column(Integer, ForeignKey('wallets.id'))
    children = relationship("DbWallet", lazy="joined", join_depth=2)
    multisig = Column(Boolean, default=True)
    cosigner_id = Column(Integer)
    key_path = Column(String(100))
    default_account_id = Column(Integer)

    __table_args__ = (
        CheckConstraint(scheme.in_(['single', 'bip32']), name='constraint_allowed_schemes'),
        CheckConstraint(encoding.in_(['base58', 'bech32']), name='constraint_default_address_encodings_allowed'),
        CheckConstraint(witness_type.in_(['legacy', 'segwit', 'p2sh-segwit']), name='wallet_constraint_allowed_types'),
    )

    def __repr__(self):
        return "<DbWallet(name='%s', network='%s'>" % (self.name, self.network_name)


class DbKeyMultisigChildren(Base):
    """
    Use many-to-many relationship for multisig keys. A multisig keys contains 2 or more child keys
    and a child key can be used in more then one multisig key.

    """
    __tablename__ = 'key_multisig_children'

    parent_id = Column(Integer, ForeignKey('keys.id'), primary_key=True)
    child_id = Column(Integer, ForeignKey('keys.id'), primary_key=True)
    key_order = Column(Integer, Sequence('key_multisig_children_id_seq'))


class DbKey(Base):
    """
    Database definitions for keys in Sqlalchemy format

    Part of a wallet, and used by transactions

    """
    __tablename__ = 'keys'
    id = Column(Integer, Sequence('key_id_seq'), primary_key=True)
    parent_id = Column(Integer, Sequence('parent_id_seq'))
    name = Column(String(80), index=True)
    account_id = Column(Integer, index=True)
    depth = Column(Integer)
    change = Column(Integer)
    address_index = Column(BigInteger)
    public = Column(String(512), index=True)
    private = Column(String(512), index=True)
    wif = Column(String(255), index=True)
    compressed = Column(Boolean, default=True)
    key_type = Column(String(10), default='bip32')
    address = Column(String(255), index=True)
    cosigner_id = Column(Integer)
    encoding = Column(String(15), default='base58')
    purpose = Column(Integer, default=44)
    is_private = Column(Boolean)
    path = Column(String(100))
    wallet_id = Column(Integer, ForeignKey('wallets.id'), index=True)
    wallet = relationship("DbWallet", back_populates="keys")
    transaction_inputs = relationship("DbTransactionInput", cascade="all,delete", back_populates="key")
    transaction_outputs = relationship("DbTransactionOutput", cascade="all,delete", back_populates="key")
    balance = Column(Numeric(25, 0, asdecimal=False), default=0)
    used = Column(Boolean, default=False)
    network_name = Column(String(20), ForeignKey('networks.name'))
    network = relationship("DbNetwork")
    multisig_parents = relationship("DbKeyMultisigChildren", backref='child_key',
                                    primaryjoin=id == DbKeyMultisigChildren.child_id)
    multisig_children = relationship("DbKeyMultisigChildren", backref='parent_key',
                                     order_by="DbKeyMultisigChildren.key_order",
                                     primaryjoin=id == DbKeyMultisigChildren.parent_id)
    latest_txid = Column(String(64))

    __table_args__ = (
        CheckConstraint(key_type.in_(['single', 'bip32', 'multisig']), name='constraint_key_types_allowed'),
        CheckConstraint(encoding.in_(['base58', 'bech32']), name='constraint_address_encodings_allowed'),
        UniqueConstraint('wallet_id', 'public', name='constraint_wallet_pubkey_unique'),
        UniqueConstraint('wallet_id', 'private', name='constraint_wallet_privkey_unique'),
        UniqueConstraint('wallet_id', 'wif', name='constraint_wallet_wif_unique'),
        UniqueConstraint('wallet_id', 'address', name='constraint_wallet_address_unique'),
    )

    def __repr__(self):
        return "<DbKey(id='%s', name='%s', wif='%s'>" % (self.id, self.name, self.wif)


class DbNetwork(Base):
    """
    Database definitions for networks in Sqlalchemy format

    """
    __tablename__ = 'networks'
    name = Column(String(20), unique=True, primary_key=True)
    description = Column(String(50))

    def __repr__(self):
        return "<DbNetwork(name='%s', description='%s'>" % (self.name, self.description)


class TransactionType(enum.Enum):
    """
    Incoming or Outgoing transaction Enumeration
    """
    incoming = 1
    outgoing = 2


class DbTransaction(Base):
    """
    Database definitions for transactions in Sqlalchemy format

    Refers to 1 or more keys which can be part of a wallet

    """
    __tablename__ = 'transactions'
    id = Column(Integer, Sequence('transaction_id_seq'), primary_key=True)
    hash = Column(String(64), index=True)
    wallet_id = Column(Integer, ForeignKey('wallets.id'), index=True)
    wallet = relationship("DbWallet", back_populates="transactions")
    witness_type = Column(String(20), default='legacy')
    version = Column(Integer, default=1)
    locktime = Column(Integer, default=0)
    date = Column(DateTime, default=datetime.datetime.utcnow)
    coinbase = Column(Boolean, default=False)
    confirmations = Column(Integer, default=0)
    block_height = Column(Integer, index=True)
    block_hash = Column(String(64), index=True)
    size = Column(Integer)
    fee = Column(Integer)
    inputs = relationship("DbTransactionInput", cascade="all,delete")
    outputs = relationship("DbTransactionOutput", cascade="all,delete")
    status = Column(String(20), default='new')
    input_total = Column(Numeric(25, 0, asdecimal=False), default=0)
    output_total = Column(Numeric(25, 0, asdecimal=False), default=0)
    network_name = Column(String(20), ForeignKey('networks.name'))
    network = relationship("DbNetwork")
    raw = Column(Text())
    verified = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint('wallet_id', 'hash', name='constraint_wallet_transaction_hash_unique'),
        CheckConstraint(status.in_(['new', 'incomplete', 'unconfirmed', 'confirmed']),
                        name='constraint_status_allowed'),
        CheckConstraint(witness_type.in_(['legacy', 'segwit']), name='transaction_constraint_allowed_types'),
    )

    def __repr__(self):
        return "<DbTransaction(hash='%s', confirmations='%s')>" % (self.hash, self.confirmations)


class DbTransactionInput(Base):
    """
    Transaction Input Table

    Relates to Transaction table and Key table

    """
    __tablename__ = 'transaction_inputs'
    transaction_id = Column(Integer, ForeignKey('transactions.id'), primary_key=True)
    transaction = relationship("DbTransaction", back_populates='inputs')
    index_n = Column(Integer, primary_key=True)
    key_id = Column(Integer, ForeignKey('keys.id'), index=True)
    key = relationship("DbKey", back_populates="transaction_inputs")
    witness_type = Column(String(20), default='legacy')
    prev_hash = Column(String(64))
    output_n = Column(BigInteger)
    script = Column(Text)
    script_type = Column(String(20), default='sig_pubkey')
    sequence = Column(Integer)
    value = Column(Numeric(25, 0, asdecimal=False), default=0)
    double_spend = Column(Boolean, default=False)

    __table_args__ = (CheckConstraint(script_type.in_(['', 'coinbase', 'sig_pubkey', 'p2sh_multisig',
                                                       'signature', 'unknown', 'p2sh_p2wpkh', 'p2sh_p2wsh']),
                                      name='transactioninput_constraint_script_types_allowed'),
                      CheckConstraint(witness_type.in_(['legacy', 'segwit', 'p2sh-segwit']),
                                      name='transactioninput_constraint_allowed_types'),)


class DbTransactionOutput(Base):
    """
    Transaction Output Table

    Relates to Transaction and Key table

    When spent is False output is considered an UTXO

    """
    __tablename__ = 'transaction_outputs'
    transaction_id = Column(Integer, ForeignKey('transactions.id'), primary_key=True)
    transaction = relationship("DbTransaction", back_populates='outputs')
    output_n = Column(BigInteger, primary_key=True)
    key_id = Column(Integer, ForeignKey('keys.id'), index=True)
    key = relationship("DbKey", back_populates="transaction_outputs")
    script = Column(Text)
    script_type = Column(String(20), default='p2pkh')
    value = Column(Numeric(25, 0, asdecimal=False), default=0)
    spent = Column(Boolean(), default=False)

    __table_args__ = (CheckConstraint(script_type.in_(['', 'p2pkh',  'multisig', 'p2sh', 'p2pk', 'nulldata',
                                                       'unknown', 'p2wpkh', 'p2wsh']),
                                      name='transactionoutput_constraint_script_types_allowed'),)


if __name__ == '__main__':
    DbInit()
