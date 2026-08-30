"""Instala os fakes das dependências pesadas ANTES de qualquer import do serviço."""

from tests_support.fakes import install_all_fakes

install_all_fakes()
