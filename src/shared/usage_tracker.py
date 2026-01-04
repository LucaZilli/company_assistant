from dataclasses import dataclass
from dataclasses import field
import typing as t


MODEL_PRICING: dict[str, dict[str, float]] = {
    'openai/gpt-4.1-mini': {'input': 0.40, 'output': 1.60, 'request': 0.0},
    'openai/gpt-4.1': {'input': 2.0, 'output': 8.0, 'request': 0.0},
    'openai/gpt-5-mini': {'input': 0.25, 'output': 2.0, 'request': 0.0},
    'openai/gpt-5.1-chat': {'input': 1.25, 'output': 10.0, 'request': 0.0},
    'google/gemini-2.5-flash': {'input': 0.30, 'output': 2.50, 'request': 0.0},
    'perplexity/sonar': {'input': 1.0, 'output': 1.0, 'request': 5.0},
    'serper': {'input': 0.0, 'output': 0.0, 'request': 1.0},
}

@dataclass
class TokenUsage:
    """Token usage for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ''
    call_type: str = ''

    @property
    def total_tokens(self) -> int:
        """Return total tokens used for this call.

        Returns:
            Total tokens for the call.
        """
        return self.input_tokens + self.output_tokens

    def calculate_cost(self) -> float:
        """Calculate cost in USD based on model pricing.

        Returns:
            The cost in USD for this usage record.
        """
        pricing = MODEL_PRICING.get(self.model)
        cost = (
            (self.input_tokens / 1_000_000) * pricing['input']
            + (self.output_tokens / 1_000_000) * pricing['output']
            + (1 / 1_000) * pricing['request']
        )
        return cost


@dataclass
class UsageTracker:
    """Tracks token usage and costs across multiple calls."""

    calls: list[TokenUsage] = field(default_factory=list)

    def add(self, usage: TokenUsage) -> TokenUsage:
        """Add a usage record.

        Args:
            usage: TokenUsage entry to store.

        Returns:
            The same TokenUsage instance.
        """
        self.calls.append(usage)
        return usage

    def add_from_langchain(self, response: t.Any, model: str, call_type: str) -> TokenUsage:
        """Extract usage from a LangChain response.

        Args:
            response: LangChain AIMessage or compatible response.
            model: Model identifier.
            call_type: Logical call type (routing, generation, search, judge).

        Returns:
            Parsed TokenUsage instance.
        """
        usage = TokenUsage(model=model, call_type=call_type)

        if hasattr(response, 'response_metadata') and response.response_metadata:
            token_usage = response.response_metadata.get('token_usage', {})
            usage.input_tokens = token_usage.get('prompt_tokens', 0) or 0
            usage.output_tokens = token_usage.get('completion_tokens', 0) or 0
        elif hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage.input_tokens = response.usage_metadata.get('input_tokens', 0) or 0
            usage.output_tokens = response.usage_metadata.get('output_tokens', 0) or 0

        self.calls.append(usage)
        return usage

    def add_from_openai(self, completion: t.Any, model: str, call_type: str) -> TokenUsage:
        """Extract usage from an OpenAI-compatible completion response.

        Args:
            completion: OpenAI completion object.
            model: Model identifier.
            call_type: Logical call type (routing, generation, search, judge).

        Returns:
            Parsed TokenUsage instance.
        """
        usage = TokenUsage(model=model, call_type=call_type)

        if hasattr(completion, 'usage') and completion.usage:
            usage.input_tokens = getattr(completion.usage, 'prompt_tokens', 0) or 0
            usage.output_tokens = getattr(completion.usage, 'completion_tokens', 0) or 0

        self.calls.append(usage)
        return usage

    def add_from_instructor(self, completion: t.Any, model: str, call_type: str) -> TokenUsage:
        """Extract usage from an Instructor completion response.

        Args:
            completion: Instructor completion object.
            model: Model identifier.
            call_type: Logical call type (routing, generation, search, judge).

        Returns:
            Parsed TokenUsage instance.
        """
        usage = TokenUsage(model=model, call_type=call_type)

        if hasattr(completion, 'usage') and completion.usage:
            usage.input_tokens = getattr(completion.usage, 'prompt_tokens', 0) or 0
            usage.output_tokens = getattr(completion.usage, 'completion_tokens', 0) or 0

        self.calls.append(usage)
        return usage

    @property
    def total_input_tokens(self) -> int:
        """Return total input tokens across calls.

        Returns:
            Sum of input tokens across tracked calls.
        """
        return sum(call.input_tokens for call in self.calls)

    @property
    def total_output_tokens(self) -> int:
        """Return total output tokens across calls.

        Returns:
            Sum of output tokens across tracked calls.
        """
        return sum(call.output_tokens for call in self.calls)

    @property
    def total_tokens(self) -> int:
        """Return total tokens across calls.

        Returns:
            Sum of total tokens across tracked calls.
        """
        return sum(call.total_tokens for call in self.calls)

    @property
    def total_cost(self) -> float:
        """Return total cost across calls.

        Returns:
            Sum of costs across tracked calls.
        """
        return sum(call.calculate_cost() for call in self.calls)

    def summary(self) -> dict[str, t.Any]:
        """Return summary statistics for tracked usage.

        Returns:
            A dictionary with totals and per-type summaries.
        """
        by_type: dict[str, dict[str, float | int]] = {}
        for call in self.calls:
            if call.call_type not in by_type:
                by_type[call.call_type] = {
                    'calls': 0,
                    'input': 0,
                    'output': 0,
                    'cost': 0.0,
                }
            by_type[call.call_type]['calls'] += 1
            by_type[call.call_type]['input'] += call.input_tokens
            by_type[call.call_type]['output'] += call.output_tokens
            by_type[call.call_type]['cost'] += call.calculate_cost()

        return {
            'total_calls': len(self.calls),
            'total_tokens': self.total_tokens,
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_cost_usd': round(self.total_cost, 6),
            'by_type': by_type,
        }

    def print_summary(self) -> None:
        """Print a formatted usage summary to stdout."""
        summary = self.summary()
        print(f"\n{'=' * 50}")
        print('💰 TOKEN USAGE & COST SUMMARY')
        print(f"{'=' * 50}")
        print(f"Total calls: {summary['total_calls']}")
        print(f"Total tokens: {summary['total_tokens']:,}")
        print(f"  Input: {summary['total_input_tokens']:,}")
        print(f"  Output: {summary['total_output_tokens']:,}")
        print(f"Total cost: ${summary['total_cost_usd']:.4f}")
        print('\nBy call type:')
        for call_type, data in summary['by_type'].items():
            tokens = data['input'] + data['output']
            print(
                f"  {call_type}: {data['calls']} calls, {tokens:,} tokens, "
                f"${data['cost']:.4f}"
            )


tracker = UsageTracker()
