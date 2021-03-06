# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import, division, print_function

"""
    Poker hand history parser module.
"""

import io
import itertools
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from datetime import datetime
import pytz
from cached_property import cached_property
from poker.card import Rank


_Player = namedtuple('_Player', 'name, stack, seat, combo')
"""Named tuple for players participating in the hand history."""

_PlayerAction = namedtuple('_PlayerAction', 'name, action, amount')
"""Named tuple for player actions on the street."""


class _BaseStreet(object):
    __metaclass__ = ABCMeta

    def __init__(self, flop):
        self.pot = None
        self.actions = None
        self.cards = None
        self._parse_cards(flop[0])
        self._parse_actions(flop[1:])
        self._all_combinations = itertools.combinations(self.cards, 2)

    @cached_property
    def is_rainbow(self):
        return all(first.suit != second.suit for first, second in self._all_combinations)

    @cached_property
    def is_monotone(self):
        return all(first.suit == second.suit for first, second in self._all_combinations)

    @cached_property
    def is_triplet(self):
        return all(first.rank == second.rank for first, second in self._all_combinations)

    @cached_property
    def has_pair(self):
        return any(first.rank == second.rank for first, second in self._all_combinations)

    @cached_property
    def has_straightdraw(self):
        return any(1 <= diff <= 3 for diff in self._get_differences())

    @cached_property
    def has_gutshot(self):
        return any(1 <= diff <= 4 for diff in self._get_differences())

    @cached_property
    def has_flushdraw(self):
        return any(first.suit == second.suit for first, second in self._all_combinations)

    @cached_property
    def players(self):
        if not self.actions:
            return None
        player_names = []
        for action in self.actions:
            player_name = action[0]
            if player_name not in player_names:
                player_names.append(player_name)
        return tuple(player_names)

    def _get_differences(self):
        return (Rank.difference(first.rank, second.rank)
                for first, second in self._all_combinations)


class _BaseHandHistory(object):
    """Abstract base class for *all* kind of parser."""
    __metaclass__ = ABCMeta

    @abstractmethod
    def __init__(self, hand_text):
        """Save raw hand history."""
        self.raw = hand_text.strip()
        self.header_parsed = False
        self.parsed = False

    @classmethod
    def from_file(cls, filename):
        with io.open(filename) as f:
            return cls(f.read())

    def __unicode__(self):
        return "<{}: #{}>" .format(self.__class__.__name__, self.ident)

    def __str__(self):
        return unicode(self).decode('utf-8')

    @property
    def board(self):
        """Calculates board from flop, turn and river."""
        board = []
        if self.flop:
            board.extend(self.flop.cards)
            if self.turn:
                board.append(self.turn)
                if self.river:
                    board.append(self.river)
        return tuple(board) if board else None

    def _parse_date(self, date_string):
        """Parse the date_string and return a datetime object as UTC."""
        date = datetime.strptime(date_string, self.date_format)
        self.date = self._TZ.localize(date).astimezone(pytz.UTC)

    def _init_seats(self, player_num):
        players = []
        for seat in range(1, player_num + 1):
            players.append(_Player(name='Empty Seat %s' % seat, stack=0, seat=seat, combo=None))

        return players

    def _get_hero_from_players(self, hero_name):
        player_names = [p.name for p in self.players]
        hero_index = player_names.index(hero_name)
        return self.players[hero_index], hero_index


class _SplittableHandHistory(_BaseHandHistory):
    """Base class for PokerStars and FullTiltPoker type hand histories, where you can split
    the hand history into sections.
    """

    def __init__(self, hand_text):
        """Split hand history by sections."""

        super(_SplittableHandHistory, self).__init__(hand_text)

        self._splitted = self._split_re.split(self.raw)

        # search split locations (basically empty strings)
        # sections[0] is before HOLE CARDS
        # sections[-1] is before SUMMARY
        self._sections = [ind for ind, elem in enumerate(self._splitted) if not elem]

    @abstractmethod
    def parse_header(self):
        """Parses only the header of a hand history. It is used for sort of looking into
        the hand history for basic informations:
            ident, date, game, game_type, limit, money_type, sb, bb, buyin, rake, currency
        """

    def parse(self):
        """Parses the body of the hand history, but first parse header if not yet parsed."""
        if not self.header_parsed:
            self.parse_header()

        self._parse_table()
        self._parse_players()
        self._parse_button()
        self._parse_hero()
        self._parse_preflop()
        self._parse_flop()
        self._parse_street('turn')
        self._parse_street('river')
        self._parse_showdown()
        self._parse_pot()
        self._parse_board()
        self._parse_winners()
        self._parse_extra()

        del self._splitted
        self.parsed = True

    @abstractmethod
    def _parse_table(self):
        pass

    @abstractmethod
    def _parse_players(self):
        pass

    @abstractmethod
    def _parse_button(self):
        pass

    @abstractmethod
    def _parse_hero(self):
        pass

    @abstractmethod
    def _parse_preflop(self):
        pass

    @abstractmethod
    def _parse_street(self):
        pass

    @abstractmethod
    def _parse_showdown(self):
        pass

    @abstractmethod
    def _parse_pot(self):
        pass

    @abstractmethod
    def _parse_board(self):
        pass

    @abstractmethod
    def _parse_winners(self):
        pass

    @abstractmethod
    def _parse_extra(self):
        pass
