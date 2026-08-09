from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def render_formula_element(element, hidden_ids):
    """
    Render a formula element.

    Handles normal elements and fractions,
    including nested elements inside fractions.
    """

    html = render_element(
        element,
        hidden_ids
    )

    return mark_safe(html)


def render_element(element, hidden_ids):
    """
    Recursively render one formula element.
    """

    element_id = str(
        element.get("id", "")
    )

    element_type = element.get(
        "type",
        ""
    )

    value = element.get(
        "value",
        ""
    )

    hidden_ids = [
        str(item)
        for item in hidden_ids
    ]


    # ==================================================
    # HIDDEN ELEMENT
    # ==================================================

    if element_id in hidden_ids:

        return f"""
            <span class="recall-element">

                <input
                    type="text"
                    name="answer_{element_id}"
                    class="recall-input"
                    autocomplete="off"
                    data-element-id="{element_id}"
                >

                <input
                    type="hidden"
                    name="hidden_element_id"
                    value="{element_id}"
                >

            </span>
        """


    # ==================================================
    # FRACTION
    # ==================================================

    if element_type == "fraction":

        numerator_html = ""

        for part in element.get(
            "numerator",
            []
        ):

            numerator_html += render_element(
                part,
                hidden_ids
            )


        denominator_html = ""

        for part in element.get(
            "denominator",
            []
        ):

            denominator_html += render_element(
                part,
                hidden_ids
            )


        return f"""
            <span class="fraction">

                <span class="fraction-numerator">
                    {numerator_html}
                </span>

                <span class="fraction-line"></span>

                <span class="fraction-denominator">
                    {denominator_html}
                </span>

            </span>
        """


    # ==================================================
    # VARIABLE
    # ==================================================

    if element_type == "variable":

        return f"""
            <span class="formula-element variable">
                {value}
            </span>
        """


    # ==================================================
    # NORMAL ELEMENT
    # ==================================================

    return f"""
        <span class="formula-element">
            {value}
        </span>
    """