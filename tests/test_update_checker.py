from types import SimpleNamespace

from modules.update_checker import check_file


def file_item(id, name, date, description, md5=None, archived=False):
    return SimpleNamespace(id=id, name=name, date_added=date, description=description, md5=md5, archived=archived)


def installed_item(id, name, date, description, md5=None):
    return SimpleNamespace(file_id=id, file_name=name, date_added=date, description=description, md5=md5)


def test_exact_file_is_up_to_date():
    installed = installed_item(1, "demo.zip", 10, "Main", "abc")
    details = SimpleNamespace(unavailable_reason=None, files=[file_item(1, "demo.zip", 10, "Main", "abc")], archived_files=[])
    assert check_file(installed, details).kind == "up_to_date"


def test_unique_new_same_label_is_update():
    installed = installed_item(1, "demo.zip", 10, "Main")
    details = SimpleNamespace(unavailable_reason=None, files=[file_item(2, "demo-v2.zip", 20, "Main")], archived_files=[])
    assert check_file(installed, details).kind == "update_available"


def test_multiple_same_label_is_ambiguous():
    installed = installed_item(1, "demo.zip", 10, "Main")
    details = SimpleNamespace(unavailable_reason=None, files=[file_item(2, "a.zip", 20, "Main"), file_item(3, "b.zip", 21, "Main")], archived_files=[])
    assert check_file(installed, details).kind == "ambiguous"
