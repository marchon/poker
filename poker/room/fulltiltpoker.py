# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import, division, print_function

import re
from decimal import Decimal
import pytz
from ..handhistory import _Player, _SplittableHandHistory, _BaseStreet, _PlayerAction
from ..card import Card
from ..hand import Combo
from ..constants import Limit, Game, GameType, Currency, Action
from .._common import _make_int


__all__ = ['FullTiltPokerHandHistory']


class _Street(_BaseStreet):
    def _parse_cards(self, boardline):
        self.cards = (Card(boardline[1:3]), Card(boardline[4:6]), Card(boardline[7:9]))

    def _parse_actions(self, actionlines):
        actions = []
        for line in actionlines:
            if line.startswith('Uncalled bet'):
                action = self._parse_uncalled(line)
            elif 'raises to' in line:
                action = self._parse_raise(line)
            elif 'wins the pot' in line:
                action = self._parse_win(line)
            elif 'mucks' in line:
                action = self._parse_muck(line)
            elif 'seconds left to act' in line:
                action = self._parse_think(line)
            elif ' ' in line:
                action = self._parse_player_action(line)
            else:
                raise
            actions.append(_PlayerAction(*action))
        self.actions = tuple(actions) if actions else None

    def _parse_uncalled(self, line):
        amount_start_index = 16
        space_after_amount_index = line.find(' ', amount_start_index)
        amount = line[amount_start_index:space_after_amount_index]
        name_start_index = line.find('to ') + 3
        name = line[name_start_index:]
        return name, Action.RETURN, Decimal(amount)

    def _parse_raise(self, line):
        first_space_index = line.find(' ')
        name = line[:first_space_index]
        amount_start_index = line.find('to ') + 3
        amount = line[amount_start_index:]
        return name, Action.RAISE, Decimal(amount)

    def _parse_win(self, line):
        first_space_index = line.find(' ')
        name = line[:first_space_index]
        first_paren_index = line.find('(')
        last_paren_index = -1
        amount = line[first_paren_index + 1:last_paren_index]
        self.pot = Decimal(amount)
        return name, Action.WIN, self.pot

    def _parse_muck(self, line):
        space_index = line.find(' ')
        name = line[:space_index]
        return name, Action.MUCK, None

    def _parse_think(self, line):
        space_index = line.find(' ')
        name = line[:space_index]
        return name, Action.THINK, None

    def _parse_player_action(self, line):
        space_index = line.find(' ')
        name = line[:space_index]
        end_action_index = line.find(' ', space_index + 1)
        # -1 means not found
        if end_action_index == -1:
            end_action_index = None  # until the end
        action = Action(line[space_index + 1:end_action_index])
        if end_action_index:
            amount = line[end_action_index + 1:]
            return name, action, Decimal(amount)
        else:
            return name, action, None


class FullTiltPokerHandHistory(_SplittableHandHistory):
    """Parses Full Tilt Poker hands the same way as PokerStarsHandHistory class."""

    date_format = '%H:%M:%S ET - %Y/%m/%d'
    tournament_level = None     # FTP hands doesn't contains tournament level information
    rake = None

    _TZ = pytz.timezone('US/Eastern')  # ET

    _split_re = re.compile(r" ?\*\*\* ?\n?|\n")
    # header patterns
    _header_re = re.compile(r"""
        ^Full[ ]Tilt[ ]Poker[ ]                                 # Poker Room
        Game[ ]\#(?P<ident>\d*):[ ]                             # Hand history id
        (?P<tournament_name>                                    # Tournament name
            \$?(?P<buyin>\d*)?                                  # buyin, not always there,
                                                                # part of tournament_name
        .*)[ ]                                                  # end of tournament_name
        \((?P<tournament_ident>\d*)\),[ ]                       # Tournament Number
        Table[ ](?P<table_name>\d*)[ ]-[ ]                      # Table name
        (?P<limit>NL|PL|FL|No Limit|Pot Limit|Fix Limit)[ ]     # limit
        (?P<game>.*?)[ ]-[ ]                                    # game
        (?P<sb>\d*)/(?P<bb>\d*)[ ]-[ ].*                        # blinds
        \[(?P<date>.*)\]$                                       # date in ET
        """, re.VERBOSE)
    _seat_re = re.compile(r"^Seat (\d): (.*) \(([\d,]*)\)$")
    _button_re = re.compile(r"^The button is in seat #(\d)$")
    _hero_re = re.compile(r"^Dealt to (?P<hero_name>.*) \[(..) (..)\]$")
    _street_re = re.compile(r"\[([^\]]*)\] \(Total Pot: (\d*)\, (\d) Players")
    _pot_re = re.compile(r"^Total pot ([\d,]*) .*\| Rake (\d*)$")
    _winner_re = re.compile(r"^Seat (?P<seat>\d): (?P<name>.*?) .*collected \((\d*)\),")
    _showdown_re = re.compile(r"^Seat (\d): (.*) showed .* and won")
    _board_re = re.compile(r"(?<=[\[ ])(..)(?=[\] ])")

    # search split locations (basically empty strings)
    # sections[0] is before HOLE CARDS
    # sections[-1] is before SUMMARY

    def parse_header(self):
        header_line = self._splitted[0]
        header_match = self._header_re.match(header_line)
        self.sb = Decimal(header_match.group('sb'))
        self.bb = Decimal(header_match.group('bb'))
        self._parse_date(header_match.group('date'))
        self.ident = header_match.group('ident')
        tournament_name = header_match.group('tournament_name')
        self.game_type = GameType.SNG if 'Sit & Go' in tournament_name else GameType.TOUR
        self.currency = Currency.USD if '$' in tournament_name else None
        self.tournament_ident = header_match.group('tournament_ident')
        self.table_name = header_match.group('table_name')
        self.limit = Limit(header_match.group('limit'))
        self.game = Game(header_match.group('game'))
        buyin = header_match.group('buyin')
        self.buyin = Decimal(buyin) if buyin else None

        self.extra = dict()
        self.extra['tournament_name'] = tournament_name

        self.header_parsed = True

    def _parse_table(self):
        # table already parsed in parse_header()
        pass

    def _parse_players(self):
        # In hh there is no indication of max_players, so init for 9.
        players = self._init_seats(9)
        for line in self._splitted[1:]:
            match = self._seat_re.match(line)
            if not match:
                break
            seat = int(match.group(1))
            players[seat - 1] = _Player(
                name=match.group(2),
                seat=seat,
                stack=_make_int(match.group(3)),
                combo=None
            )
        self.max_players = seat
        self.players = players[:seat]  # cut off unneccesary seats

    def _parse_button(self):
        # one line before the first split.
        button_line = self._splitted[self._sections[0] - 1]
        button_seat = int(self._button_re.match(button_line).group(1))
        self.button = self.players[button_seat - 1]

    def _parse_hero(self):
        hole_cards_line = self._splitted[self._sections[0] + 2]
        match = self._hero_re.match(hole_cards_line)
        hero, hero_index = self._get_hero_from_players(match.group('hero_name'))
        self.hero = self.players[hero_index] = hero._replace(
            combo=Combo(match.group(2) + match.group(3))
        )

        if self.button.name == self.hero.name:
            self.button = self.hero

    def _parse_preflop(self):
        start = self._sections[0] + 3
        stop = self._sections[1]
        self.preflop_actions = tuple(self._splitted[start:stop])

    def _parse_flop(self):
        try:
            start = self._splitted.index('FLOP')
        except ValueError:
            self.flop = None
            return
        stop = next(v for v in self._sections if v > start)
        floplines = self._splitted[start + 1:stop]
        self.flop = _Street(floplines)

    def _parse_street(self, street):
        try:
            start = self._splitted.index(street.upper()) + 1
            self._parse_streetline(start, street)
            stop = next(v for v in self._sections if v > start)
            street_actions = self._splitted[start + 1:stop]
            setattr(self, "{}_actions".format(street), tuple(street_actions)
                    if street_actions else None)
        except ValueError:
            setattr(self, street, None)
            setattr(self, '{}_actions'.format(street), None)
            setattr(self, '{}_pot'.format(street), None)
            setattr(self, '{}_num_players'.format(street), None)

    def _parse_showdown(self):
        self.show_down = 'SHOW DOWN' in self._splitted

    def _parse_pot(self):
        potline = self._splitted[self._sections[-1] + 2]
        match = self._pot_re.match(potline.replace(',', ''))
        self.total_pot = int(match.group(1))

    def _parse_board(self):
        boardline = self._splitted[self._sections[-1] + 3]
        if not boardline.startswith('Board'):
            return
        cards = self._board_re.findall(boardline)
        self.turn = Card(cards[3]) if len(cards) > 3 else None
        self.river = Card(cards[4]) if len(cards) > 4 else None

    def _parse_winners(self):
        winners = set()
        start = self._sections[-1] + 4
        for line in self._splitted[start:]:
            if not self.show_down and "collected" in line:
                match = self._winner_re.match(line)
                winners.add(match.group('name'))
            elif self.show_down and "won" in line:
                match = self._showdown_re.match(line)
                winners.add(match.group('name'))

        self.winners = tuple(winners)

    def _parse_extra(self):
        # tournament name already parsed in header
        for street in ('turn', 'river'):
            try:
                start = self._splitted.index(street.upper()) + 1
                self._parse_streetline(start, street)
            except ValueError:
                self.extra['{}_pot'.format(street)] = None
                self.extra['{}_num_players'.format(street)] = None

    def _parse_streetline(self, start, street):
        """Parse pot, num players."""

        # Exceptions caught in _parse_street.
        board_line = self._splitted[start]
        match = self._street_re.search(board_line)
        pot = match.group(2)
        self.extra['{}_pot'.format(street)] = Decimal(pot)

        num_players = int(match.group(3))
        self.extra['{}_num_players'.format(street)] = num_players
