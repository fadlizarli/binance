"""
main_multipair.py — Entry point untuk multi-pair bot
Cara pakai: python main_multipair.py
Atau ganti isi main.py dengan file ini
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.bot_engine_multipair import MultipairBotEngine

if __name__ == "__main__":
    bot = MultipairBotEngine()
    bot.start()

