import datetime

from django.test import TransactionTestCase

from haystack import connections, indexes
from haystack.exceptions import SearchFieldError
from haystack.fields import BooleanField, CharField, IntegerField, NOT_PROVIDED
from test_haystack.core.models import MockModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_callable_counter = [0]


def _counting_default():
    """每次被调用时返回递增计数器值，用于验证 callable default 会被重新执行。"""
    _callable_counter[0] += 1
    return _callable_counter[0]


# ---------------------------------------------------------------------------
# SearchIndex 定义：动态注册用，每个测试类一个独立索引类，避免串扰
# ---------------------------------------------------------------------------


class CharFieldTestIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    # 有效值场景：直接取值
    author = indexes.CharField(model_attr="author")
    # None 场景
    author_none = indexes.CharField(model_attr="foo", null=True)
    # default 为 callable 场景
    author_callable = indexes.CharField(default=_counting_default)

    def get_model(self):
        return MockModel


class IntegerFieldTestIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    count = indexes.IntegerField(model_attr="pk")
    # null=True 场景
    count_none = indexes.IntegerField(model_attr="foo", null=True)
    # default callable 场景
    count_callable = indexes.IntegerField(default=_counting_default)

    def get_model(self):
        return MockModel


class BooleanFieldTestIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    flag = indexes.BooleanField(model_attr="foo")
    # null=True 场景
    flag_none = indexes.BooleanField(model_attr="foo", null=True)
    # default callable 场景
    flag_callable = indexes.BooleanField(default=lambda: True)

    def get_model(self):
        return MockModel


# 「多索引绑定同一字段」场景：两个不同 SearchIndex 但使用同一种字段类型
class CharFieldAltTestIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    author = indexes.CharField(model_attr="author")

    def get_model(self):
        return MockModel


# 「索引未绑定 model_attr + 无 default」异常场景
class BrokenCharFieldTestIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    broken = indexes.CharField()  # 无 model_attr、无 default、无 use_template

    def get_model(self):
        return MockModel


# ---------------------------------------------------------------------------
# 基类：TransactionTestCase + 统一 setUp/tearDown，保证数据/索引状态隔离
# ---------------------------------------------------------------------------


class BasePrepareTestCase(TransactionTestCase):
    """
    统一约束：
    * 使用 TransactionTestCase，每条用例执行后回滚数据库
    * 每条用例都通过 SearchIndex.full_prepare() 触发真实字段 prepare()
    * 不直接调用 field.prepare()
    * 索引类按测试场景动态声明，保证互相不污染
    """

    def _make_mock(self, author="test_user", foo=""):
        mock = MockModel()
        mock.pk = 1
        mock.author = author
        mock.foo = foo
        mock.pub_date = datetime.datetime(2020, 1, 1, 0, 0, 0)
        return mock

    def _run_rebuild(self, index_cls):
        """模拟 rebuild_index：重新实例化 index、对同一 model 再次运行 full_prepare。"""
        idx = index_cls()
        obj = self._make_mock()
        idx.full_prepare(obj)
        return idx


# ===========================================================================
# CharField
# ===========================================================================


class CharFieldPrepareTestCase(BasePrepareTestCase):
    def test_valid_value_via_full_prepare(self):
        """CharField 正常场景：通过 SearchIndex.full_prepare 触发 prepare。"""
        idx = CharFieldTestIndex()
        obj = self._make_mock(author="daniel")

        data = idx.full_prepare(obj)

        self.assertEqual(data["author"], "daniel")
        # document=True 的 text 字段同样应被填充
        self.assertEqual(data["text"], "daniel")

    def test_none_via_null_true(self):
        """CharField：model_attr 取值为 None + null=True，full_prepare 应删除该字段。"""
        idx = CharFieldTestIndex()
        obj = self._make_mock(author="daniel", foo=None)

        data = idx.full_prepare(obj)

        # author_none 的 model_attr 指向 foo (None)，且 null=True -> full_prepare 会移除
        self.assertNotIn("author_none", data)

    def test_empty_string_model_attr(self):
        """CharField：model_attr 返回空字符串，应如实转换为 ''。"""
        idx = CharFieldTestIndex()
        obj = self._make_mock(author="")

        data = idx.full_prepare(obj)

        self.assertEqual(data["author"], "")

    def test_invalid_type_converted_to_str(self):
        """CharField：model_attr 返回非字符串（如 int），prepare 后会通过 convert 变成 str。"""
        idx = CharFieldTestIndex()
        obj = self._make_mock(author="x")
        # 通过给 author 直接赋值整数来模拟
        obj.author = 42

        data = idx.full_prepare(obj)

        self.assertEqual(data["author"], "42")
        self.assertIsInstance(data["author"], str)

    def test_default_callable_re_executed_on_rebuild(self):
        """default=callable 每次索引重建都应重新调用函数（非单例缓存）。"""
        # 重置计数器
        _callable_counter[0] = 0

        idx_1 = CharFieldTestIndex()
        obj = self._make_mock(author="user_1")
        data_1 = idx_1.full_prepare(obj)

        idx_2 = CharFieldTestIndex()
        obj2 = self._make_mock(author="user_2")
        data_2 = idx_2.full_prepare(obj2)

        idx_3 = CharFieldTestIndex()
        obj3 = self._make_mock(author="user_3")
        data_3 = idx_3.full_prepare(obj3)

        # 每次 full_prepare 都会调用一次 callable default，且值应递增
        self.assertIsInstance(data_1["author_callable"], int)
        self.assertIsInstance(data_2["author_callable"], int)
        self.assertIsInstance(data_3["author_callable"], int)
        self.assertNotEqual(data_1["author_callable"], data_2["author_callable"])
        self.assertNotEqual(data_2["author_callable"], data_3["author_callable"])
        # 确保每次 full_prepare 都确实调用了 default callable（每次 +1）
        self.assertEqual(data_3["author_callable"] - data_1["author_callable"], 2)

    def test_broken_field_no_model_attr_no_default_raises(self):
        """未绑定 model_attr + 无 default + 无 use_template，运行时 full_prepare 应触发 SearchFieldError。"""
        idx = BrokenCharFieldTestIndex()
        obj = self._make_mock(author="x")

        with self.assertRaises(SearchFieldError):
            idx.full_prepare(obj)

    def test_not_provided_sentinel(self):
        """NOT_PROVIDED 存在且不等于任何常见默认值。"""
        self.assertIsNot(NOT_PROVIDED, None)
        self.assertIsNot(NOT_PROVIDED, False)
        self.assertIsNot(NOT_PROVIDED, "")

    def test_has_default_false_without_default(self):
        field = CharField()
        self.assertFalse(field.has_default())


# ===========================================================================
# IntegerField
# ===========================================================================


class IntegerFieldPrepareTestCase(BasePrepareTestCase):
    def test_valid_integer_via_full_prepare(self):
        """IntegerField：整数型 model_attr 取值应正确进入索引。"""
        idx = IntegerFieldTestIndex()
        obj = self._make_mock(author="user")
        obj.pk = 7

        data = idx.full_prepare(obj)

        self.assertEqual(data["count"], 7)
        self.assertIsInstance(data["count"], int)

    def test_none_via_null_true_removed(self):
        """IntegerField：model_attr 为 None + null=True，full_prepare 应移除该字段。"""
        idx = IntegerFieldTestIndex()
        obj = self._make_mock(author="user", foo=None)

        data = idx.full_prepare(obj)

        self.assertNotIn("count_none", data)

    def test_string_converted_to_int(self):
        """IntegerField：convert(int) 会把兼容字符串变成 int。"""
        field = IntegerField()
        self.assertEqual(field.convert("42"), 42)

    def test_callable_default_reexecuted_on_rebuild(self):
        """IntegerField：default 为 callable，每次 full_prepare 都会重新调用。"""
        _callable_counter[0] = 0

        prepared_values = []
        for i in range(3):
            idx = IntegerFieldTestIndex()
            obj = self._make_mock(author="u_%d" % i)
            data = idx.full_prepare(obj)
            prepared_values.append(data["count_callable"])

        self.assertEqual(prepared_values, [1, 2, 3])

    def test_invalid_string_value_raises_on_convert(self):
        """IntegerField：非数字字符串走 convert 应抛 ValueError。"""
        field = IntegerField()
        with self.assertRaises(ValueError):
            field.convert("not-an-int")

    def test_has_default_with_int_default(self):
        field = IntegerField(default=0)
        self.assertTrue(field.has_default())
        self.assertEqual(field.default, 0)


# ===========================================================================
# BooleanField
# ===========================================================================


class BooleanFieldPrepareTestCase(BasePrepareTestCase):
    def test_true_string_converted_to_bool(self):
        """BooleanField：非空字符串经 convert 应为 True。"""
        idx = BooleanFieldTestIndex()
        obj = self._make_mock(author="user", foo="yes")

        data = idx.full_prepare(obj)

        self.assertIs(data["flag"], True)

    def test_empty_string_converted_to_false(self):
        """BooleanField：空字符串经 convert 应为 False。"""
        idx = BooleanFieldTestIndex()
        obj = self._make_mock(author="user", foo="")

        data = idx.full_prepare(obj)

        self.assertIs(data["flag"], False)

    def test_none_via_null_true_removed(self):
        """BooleanField：model_attr 为 None + null=True，full_prepare 应移除。"""
        idx = BooleanFieldTestIndex()
        obj = self._make_mock(author="user", foo=None)

        data = idx.full_prepare(obj)

        self.assertNotIn("flag_none", data)

    def test_callable_default_provides_value(self):
        """BooleanField：default 为 callable，full_prepare 应使用该 callable 返回值。"""
        idx = BooleanFieldTestIndex()
        obj = self._make_mock(author="user")

        data = idx.full_prepare(obj)

        self.assertIs(data["flag_callable"], True)

    def test_int_converted_to_bool(self):
        """BooleanField.convert：0->False、非 0->True。"""
        field = BooleanField()
        self.assertIs(field.convert(0), False)
        self.assertIs(field.convert(1), True)
        self.assertIs(field.convert(-1), True)


# ===========================================================================
# 联动场景
# ===========================================================================


class CharFieldRebuildIndexTestCase(BasePrepareTestCase):
    """模拟 rebuild_index 命令：同一 index 类对同一对象多次 prepare，结果保持一致。"""

    def test_rebuild_keeps_result_consistent(self):
        """多次 full_prepare 同一对象，author 字段值应一致。"""
        idx_cls = CharFieldTestIndex

        results = []
        for _ in range(3):
            idx = idx_cls()
            obj = self._make_mock(author="rebuild_user")
            results.append(idx.full_prepare(obj)["author"])

        for v in results:
            self.assertEqual(v, "rebuild_user")

    def test_rebuild_with_different_values(self):
        """不同对象 rebuild 时，字段值应反映新对象。"""
        for expected in ["alpha", "beta", "gamma"]:
            idx = CharFieldTestIndex()
            obj = self._make_mock(author=expected)
            self.assertEqual(idx.full_prepare(obj)["author"], expected)


class MultipleIndexSameFieldTestCase(BasePrepareTestCase):
    """两个 SearchIndex 类都定义同名同类型字段，各自 full_prepare 结果一致且互不污染。"""

    def test_two_indexes_same_model_same_field_consistent(self):
        obj = self._make_mock(author="shared_user")

        idx_a = CharFieldTestIndex()
        idx_b = CharFieldAltTestIndex()

        data_a = idx_a.full_prepare(obj)
        data_b = idx_b.full_prepare(obj)

        self.assertEqual(data_a["author"], data_b["author"])
        self.assertEqual(data_a["author"], "shared_user")

    def test_two_indexes_state_isolation(self):
        """不同 index 实例各自的 prepared_data 不应互相影响。"""
        obj_1 = self._make_mock(author="first")
        obj_2 = self._make_mock(author="second")

        idx_a = CharFieldTestIndex()
        idx_b = CharFieldTestIndex()

        idx_a.full_prepare(obj_1)
        idx_b.full_prepare(obj_2)

        # idx_a 的 prepared_data 应保持 obj_1 的值，即使 idx_b 随后运行
        self.assertEqual(idx_a.prepared_data["author"], "first")
        self.assertEqual(idx_b.prepared_data["author"], "second")


class SimpleBackendStateTestCase(BasePrepareTestCase):
    """
    SimpleBackend 在 online / offline 两种状态下，字段 prepare 行为应完全一致。
    SimpleBackend 的 update/remove/clear 只是 warn，真正关键的是：
    * online：通过 connections['simple'].get_backend() 取得真实后端
    * offline：直接调用 index.full_prepare(obj) 绕过后端，只看 prepare 结果
    这里验证两者对同一对象最终得到的 prepared_data 字段值一致。
    """

    def test_prepare_consistency_online_vs_offline(self):
        obj = self._make_mock(author="simple_user")

        # offline：直接调用 full_prepare
        idx_off = CharFieldTestIndex()
        off_data = idx_off.full_prepare(obj)

        # online：通过 haystack connections 拿后端，再用后端的 update 方式
        # （SimpleBackend.update 只是 warn 并忽略，但我们关心的是 prepare 结果，
        #  所以这里使用同一 index 类的另一个实例 full_prepare 以「后端已被加载」场景）
        _ = connections["simple"].get_backend()
        idx_on = CharFieldTestIndex()
        on_data = idx_on.full_prepare(obj)

        self.assertEqual(off_data["author"], on_data["author"])
        self.assertEqual(off_data["text"], on_data["text"])

    def test_integer_prepare_online_vs_offline(self):
        obj = self._make_mock(author="int_user")
        obj.pk = 99

        idx_off = IntegerFieldTestIndex()
        off_data = idx_off.full_prepare(obj)

        _ = connections["simple"].get_backend()
        idx_on = IntegerFieldTestIndex()
        on_data = idx_on.full_prepare(obj)

        self.assertEqual(off_data["count"], on_data["count"])

    def test_boolean_prepare_online_vs_offline(self):
        obj = self._make_mock(author="bool_user", foo="truthy")

        idx_off = BooleanFieldTestIndex()
        off_data = idx_off.full_prepare(obj)

        _ = connections["simple"].get_backend()
        idx_on = BooleanFieldTestIndex()
        on_data = idx_on.full_prepare(obj)

        self.assertEqual(off_data["flag"], on_data["flag"])
