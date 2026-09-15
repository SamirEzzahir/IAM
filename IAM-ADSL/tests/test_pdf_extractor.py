from iam_adsl.services.pdf_extractor import classify_cuivre_row


def test_accepts_eligible_etude_cmd() -> None:
    cmd, classification, reason = classify_cuivre_row(
        ccna="",
        etat="EI",
        dde_wiam="D12345",
        dde_sara="139702926",
        mode="etude",
    )

    assert (cmd, classification, reason) == (
        "139702926",
        "cuivre_degroupage_adsl",
        "",
    )


def test_ignores_non_cuivre_row() -> None:
    cmd, classification, reason = classify_cuivre_row(
        ccna="FO",
        etat="VA",
        dde_wiam="D12345",
        dde_sara="139702926",
        mode="va",
    )

    assert cmd is None
    assert classification is None
    assert reason == "ccna_not_empty"
