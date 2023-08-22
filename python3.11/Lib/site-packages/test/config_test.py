"""配置文件生成测试"""

import unittest
import pathlib
import shutil
import os

from bing_translation_for_python import Translator
from bing_translation_for_python import setting

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config(unittest.TestCase):

    def setUp(self):
        self.save_dir = os.path.join(BASE_DIR, 'test_files')

    def tearDown(self):
        # 清扫文件
        try:
            shutil.rmtree(self.save_dir)
        except FileNotFoundError:
            pass

    def test_save_config(self):
        config = setting.Config(self.save_dir)
        # Translator 接受 config对象作为参数
        Translator('en', config=config)

        # 检测文件夹是否被自动创建
        try:
            files_dir = pathlib.Path(self.save_dir)
            files = os.listdir(files_dir)
            if not(files_dir.is_dir() and len(files) > 0):
                self.fail("没有找到本地配置文件文件")
        except FileNotFoundError:
            self.fail(F'检查目录:\n{self.save_dir}\n是否是一个文件夹')

    def test_read_config(self):
        setting.Config.save(
            'config.ini', self.save_dir,
            {
                "test": {'test-check': 'True'}
            }
        )

        config = setting.Config(self.save_dir)

        if 'test' not in config.tgt_lang:
            self.fail('未能从本地文件读取数据')
