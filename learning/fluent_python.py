#!/usr/bin/env python3

import collections
from random import choice

class FrenchDeck:
    ranks = [str(n) for n in range(2, 11)] + list("JQKA")
    suits = "spades diamonds clubs hearts".split()

    def __init__(self):
        self._cards = [Card(rank, suit) for suit in self.suits for rank in self.ranks]

    def __len__(self):
        return len(self._cards)

    def __getitem__(self, position):
        return self._cards[position]

Card = collections.namedtuple("Card", ["rank", "suit"])
deck = FrenchDeck()
suit_values = dict(spades=3, hearts=2, diamonds=1, clubs=0)

def print_berr_card(self):
    beer_card = Card("7", "diamonds")
    print(beer_card)

def print_len():
    print(len(deck))

def print_choice_card():
    print(choice(deck))

def spades_high(card):
    rank_value = FrenchDeck.ranks.index(card.rank)
    return rank_value * len(suit_values) + suit_values[card.suit]

def print_ordered():
    for card in sorted(deck, key=spades_high):
        print(card)

# print_choice_card()
print_ordered()
