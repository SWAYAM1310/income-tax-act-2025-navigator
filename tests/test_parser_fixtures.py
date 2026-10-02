"""Fixtures from the project brief plus cases found while building the parser."""


def test_definition_cross_reference_2_1(parsed):
    p = parsed["provisions"]["s2(1)"]
    assert p["text"] == '"accountant" shall have the meaning assigned to it in section 515(3)(b);'
    assert p["page_start"] == 2
    refs = [x for x in parsed["xrefs"] if x["from_id"] == "s2(1)"]
    assert [(x["raw"], x["to_id"], x["resolution"]) for x in refs] == [
        ("section 515(3)(b)", "s515(3)(b)", "exact")]
    target = parsed["provisions"]["s515(3)(b)"]
    assert target["text"].startswith('"accountant" means a chartered accountant')


def test_definition_lookup_2_5(parsed):
    prov = parsed["provisions"]
    p = prov["s2(5)"]
    assert p["text"].startswith('"agricultural income" means')
    assert p["children"][:4] == ["s2(5)(a)", "s2(5)(b)", "s2(5)(c)", "s2(5)(d)"]
    assert prov["s2(5)(a)"]["text"].startswith("any rent or revenue derived from a land")
    assert prov["s2(5)(b)"]["children"] == ["s2(5)(b)(i)", "s2(5)(b)(ii)", "s2(5)(b)(iii)"]
    # "(b)(ii) and (iii) is carried on" is a wrapped cross-reference, not a new clause (b)
    assert "is carried on, where such building" in prov["s2(5)(c)"]["text"]


def test_tds_table_insurance_commission_393_1_i(parsed):
    row = parsed["rows"]["s393:tbl1#1(i)"]
    assert row["row_heading"] == "Commission or brokerage"
    assert "soliciting or procuring insurance business" in row["cells"]["Nature of income or sum"]
    assert row["cells"]["Payer"] == "Any person."
    assert row["rate"] == "Rates in force."
    assert row["threshold"] == "Rs. 20,000."
    assert row["page_start"] == 456
    assert parsed["tables"]["s393:tbl1"]["title"] == "FOR PAYMENTS TO RESIDENT"


def test_table_row_split_across_pages_393_3_iii(parsed):
    row = parsed["rows"]["s393:tbl1#3(iii)"]
    assert "compulsory acquisition" in row["cells"]["Nature of income or sum"]
    assert row["rate"] == "10%"
    assert row["threshold"] == "Rs. 5,00,000."
    assert row["page_start"] == 457


def test_section_393_has_five_tables(parsed):
    titles = [parsed["tables"][f"s393:tbl{k}"]["title"] for k in range(1, 6)]
    assert titles == ["FOR PAYMENTS TO RESIDENT", "FOR PAYMENTS TO NON-RESIDENT",
                      "FOR PAYMENTS TO ANY PERSON", "FOR NO DEDUCTION AT SOURCE",
                      "DECLARATION FOR NO DEDUCTION AT SOURCE"]


def test_footnote_linkage_2_32(parsed):
    fn = next(a for a in parsed["amendments"] if a["key"].startswith("1@"))
    assert fn["linked_nodes"] == ["s2(32)"]
    assert fn["type"] == "substituted"
    assert fn["amending_act"] == "Act No. 4 of 2026"
    assert fn["effective_date"] == "1-4-2026"
    assert fn["prior_text"].startswith('(32) "co-operative society" means a co-operative society')
    assert parsed["provisions"]["s2(32)"]["is_amended"]
    # the endnote sits on p.10 while the amended clause is on p.4
    assert fn["page"] == 10 and parsed["provisions"]["s2(32)"]["page_start"] == 4


def test_omission_and_exclusion_list_2_40(parsed):
    by_label = {a["label"]: a for a in parsed["amendments"] if a["page"] < 20}
    assert by_label["2"]["type"] == "omitted" and by_label["2"]["linked_nodes"] == ["s2(40)(f)"]
    # "but does not include— (i)...(v)" belongs to clause (40), as the endnote's own wording
    # ("sub-clause (v)") confirms
    assert by_label["3"]["linked_nodes"] == ["s2(40)(v)"]


def test_chapter_part_reference_resolves(parsed):
    refs = [x for x in parsed["xrefs"] if x["from_id"] == "s2(4)" and x["ref_type"] == "part"]
    assert refs and refs[0]["to_id"] == "ch:XIX:C"
    assert parsed["provisions"]["ch:XIX:C"]["heading"] == "Advance payment of tax"
