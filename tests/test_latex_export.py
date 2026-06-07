from tools import latex_export


def test_latex_cover_letter_template_owns_date_and_signature():
    template = latex_export._TEX_TEMPLATE

    assert "{date}" in template
    assert "\\noindent Regards," not in template
    assert "Kindest Regards," in template
    assert "\\name" in template.split("Kindest Regards,")[-1]