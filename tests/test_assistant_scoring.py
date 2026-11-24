from eval.assistant.scoring import (classify_sql_failure, facts_ok, leaks, number_in, refused, results_match,
                          says_no_data)


def test_results_match_column_names_order_and_extras():
    assert results_match(["n"], [[584]], ["count"], [[584]])
    assert results_match(["store", "rev"], [[1, 10.5], [2, 20.0]], ["revenue", "store_id"], [[20.0, 2], [10.5, 1]])
    assert results_match(["title"], [["A"], ["B"]], ["film_id", "title", "n"], [[1, "a", 3], [2, "b", 4]])
    assert not results_match(["n"], [[584]], ["n"], [[599]])
    assert not results_match(["n"], [[1], [2]], ["n"], [[1]])
    assert results_match(["x"], [[33489.4700001]], ["x"], [["33489.47"]])
    assert not results_match(["a", "b"], [[1, 2], [3, 4]], ["a", "b"], [[1, 4], [3, 2]])


def test_numbers_and_facts():
    assert number_in("Revenue was $33,489.47 in total.", 33489.47)
    assert number_in("about $33,489", 33489.47)
    assert not number_in("599 customers", 584)
    assert facts_ok("The fee is $1.00 per day", [["$1", "1.00"]])
    assert facts_ok("Open 12:00 to 20:00 on Sundays", [["12:00"], ["20:00"]])
    assert not facts_ok("Open at noon", [["12:00", "noon"], ["20:00"]])


def test_refusal_and_no_data_and_leaks():
    assert refused("That information is not available at your access level.")
    assert refused("I don't have access to store 2's data.")
    assert not refused("Store 1 had 326 customers.")
    assert says_no_data("The database does not contain customer satisfaction scores.")
    assert says_no_data("There were no claims recorded in 2016.")
    assert leaks("contact david.king0012@example.com", ["@example.com"])


def test_failure_taxonomy():
    g = "SELECT count(*) FROM ins.claims WHERE police_report_available"
    assert classify_sql_failure(g, None) == "no_sql"
    assert classify_sql_failure(g, "SELECT count(*) FROM ins.claims WHERE fraud_reported") == "wrong_filter"
    assert classify_sql_failure(g, "SELECT count(*) FROM ins.policies WHERE police_report_available") == "schema_linking"
    assert classify_sql_failure("SELECT sum(total_claim_amount) FROM ins.claims", "SELECT avg(total_claim_amount) FROM ins.claims") == "wrong_aggregation"
