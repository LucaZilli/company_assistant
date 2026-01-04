def get_safety_prompt() -> str:
    """Return safety guidelines for the LLM.

    Returns:
        A formatted safety guideline string.
    """
    return (
        'SAFETY GUIDELINES:\n'
        '- Do not provide information that could be used for illegal activities\n'
        '- Do not help with hacking, exploits, or security attacks\n'
        '- Do not provide medical, legal, or financial advice as a professional\n'
        '- Decline requests for private personal data about real individuals\n'
        '- If unsure about safety, err on the side of caution and decline\n'
    )
