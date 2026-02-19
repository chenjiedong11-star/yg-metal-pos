#!/usr/bin/env python3
"""
Smoke test — verifies project integrity without launching Streamlit.
Run: python3 tests/smoke_test.py
"""

import sys
import os
import py_compile
import glob
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_compile_all():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors = []
    count = 0
    for f in sorted(glob.glob(os.path.join(root, "**", "*.py"), recursive=True)):
        if "__pycache__" in f:
            continue
        count += 1
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    assert not errors, f"Compile errors:\n" + "\n".join(errors)
    print(f"  [PASS] {count} .py files compile OK")


def test_imports():
    mods = [
        "core.config", "core.state", "core.utils",
        "db.connection", "db.schema", "db.repo_ticketing",
        "db.repo_customers", "db.repo_products",
        "services.ticketing_service", "services.report_service", "services.export_service",
        "components.keypad", "components.printer", "components.navigation",
        "ui.page_ticketing", "ui.page_manage", "ui.page_report",
    ]
    for m in mods:
        __import__(m)
    print(f"  [PASS] {len(mods)} modules imported OK")


def test_db_init_and_tables():
    from db.schema import init_db
    from db.connection import get_connection

    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in cur.fetchall()}

    required = {"clients", "operators", "material_categories", "materials",
                "receipts", "receipt_lines", "settings"}
    missing = required - tables
    assert not missing, f"Missing tables: {missing}"
    print(f"  [PASS] All required DB tables exist: {sorted(required)}")


def test_categories_and_materials():
    from db.repo_products import get_categories, get_materials
    cats = get_categories()
    assert len(cats) > 0, "No categories found"
    mats = get_materials()
    assert len(mats) > 0, "No materials found"
    print(f"  [PASS] {len(cats)} categories, {len(mats)} materials in DB")


def test_crud_category():
    from db.repo_products import add_category, delete_category, get_categories
    cats_before = len(get_categories())
    new_id = add_category("__test_cat__", sort_order=999)
    assert new_id > 0
    cats_after = len(get_categories())
    assert cats_after == cats_before + 1
    ok = delete_category(new_id)
    assert ok, "Could not delete test category"
    assert len(get_categories()) == cats_before
    print("  [PASS] Category CRUD (add/delete) works")


def test_crud_material():
    from db.repo_products import (
        get_categories, add_material, update_material,
        delete_material, restore_material, get_all_materials_df,
    )
    cats = get_categories()
    cat_id = int(cats.iloc[0]["id"])
    mid = add_material(cat_id, "__TEST__", "__test_mat__", "LB", 1.23, 0.0, 9.99)
    assert mid > 0
    update_material(mid, 2.34, 0.0, 9.99)
    delete_material(mid)
    df = get_all_materials_df()
    row = df[df["id"] == mid]
    assert len(row) == 1 and int(row.iloc[0]["deleted"]) == 1
    restore_material(mid)
    delete_material(mid)
    print("  [PASS] Material CRUD (add/update/delete/restore) works")


def test_clients():
    from db.repo_customers import get_clients, save_customer
    c = save_customer("__SmokeTest__", "000-000-0000")
    assert len(c) == 6
    df = get_clients()
    assert any(df["name"] == "__SmokeTest__")
    print("  [PASS] Client save & query works")


def test_calc_line():
    from core.utils import calc_line
    net, total = calc_line("0.50", "100", "10")
    assert net == 90.0 and abs(total - 45.0) < 0.01, f"Unexpected: net={net}, total={total}"
    print("  [PASS] calc_line(0.50, 100, 10) → net=90, total=45.00")


def test_state_init():
    import streamlit as st
    from core.state import ss_init, bump_receipt_ver, STEP_SELECT_ITEM
    ss_init("test@example.com")
    assert st.session_state.active_step == STEP_SELECT_ITEM
    old_ver = st.session_state._receipt_edit_ver
    bump_receipt_ver()
    assert st.session_state._receipt_edit_ver == old_ver + 1
    print("  [PASS] ss_init + bump_receipt_ver work correctly")


def main():
    tests = [
        test_compile_all,
        test_imports,
        test_db_init_and_tables,
        test_categories_and_materials,
        test_crud_category,
        test_crud_material,
        test_clients,
        test_calc_line,
        test_state_init,
    ]
    passed = 0
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    if failed:
        sys.exit(1)
    else:
        print("ALL SMOKE TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
