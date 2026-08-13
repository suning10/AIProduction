# Summary


## Note 1, @overload + ...

- only used for type check during developing 
  - tell pyright that the method can return either A or B
  - not being used during runtime 

- ... 
  - commonly used with @overload 

- Union
  - Either A or B
```python
 @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        response_format: None = ...,
        **model_kwargs: Any,
    ) -> BaseMessage: ...

    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        *,
        response_format: Type[T],
        **model_kwargs: Any,
    ) -> T: ...

    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        **model_kwargs: Any,
    ) -> Union[BaseMessage, BaseModel]:
```

## Note 2, @Retry from tentacy 

- key args:
  - stop, when to stop 
  - wait, set to exponential 
  - retry, only retry on certain errors 
  - reraise 
```python
    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
```

## Note 3 strategy pattern in python 

- switch to the next model + retry same model 
- more flexible instead of fix + 1 and can implement logic 
.\


1. step 1 
```python
# define advance, default 
def _override_target(idx: int) -> Any:
    base = LLMRegistry.get(LLMRegistry.LLMS[idx]["name"], **model_kwargs)
    return base.with_structured_output(response_format) if response_format else base

def _default_target(_: int) -> Any:
    return self._llm

def _default_advance(_: int) -> Optional[int]:
    return self._current_model_index if self._switch_to_next_model() else None
```
2. step 2
```python
# call it 
        if model_name or response_format or model_kwargs:
            all_names = LLMRegistry.get_all_names()
            if model_name and model_name not in all_names:
                logger.error("requested_model_not_found", model_name=model_name)
                raise ValueError(
                    f"model '{model_name}' not found in registry. available models: {', '.join(all_names)}"
                )

            start = all_names.index(model_name) if model_name else self._current_model_index
            total = len(LLMRegistry.LLMS)
            get_target: Callable[[int], Any] = _override_target

            def _override_advance(idx: int) -> Optional[int]:
                return (idx + 1) % total

            advance: Callable[[int], Optional[int]] = _override_advance
        else:
            start = self._current_model_index
            get_target = _default_target
            advance = _default_advance

        return await self._fallback_loop(messages, start, get_target, advance)
# in _fallback_loop
# defines when to current one to use and what is next one to try
            try:
                return await self._invoke_with_retry(get_target(current), messages)
            except OpenAIError as e:
                last_error = e
                logger.error(
                    "llm_call_failed_after_retries",
                    model=current_name,
                    models_tried=models_tried,
                    total_models=total,
                    error=str(e),
                )
                if models_tried >= total:
                    logger.error(
                        "all_models_failed", models_tried=models_tried, starting_model=LLMRegistry.LLMS[start]["name"]
                    )
                    break
                next_idx = advance(current)
                if next_idx is None:
                    logger.error("failed_to_switch_to_next_model")
                    break
                current = next_idx
```

>**Compare With Java**.\
> Strategy Pattern In Java.\

```Java
public interface PaymentStrategy {
    void pay(double amount);
}
```
```Java
public class CreditCardPayment implements PaymentStrategy {
    private String cardNumber;

    public CreditCardPayment(String cardNumber) {
        this.cardNumber = cardNumber;
    }

    @Override
    public void pay(double amount) {
        System.out.println("Paid $" + amount + " using Credit Card ending in " + cardNumber.substring(cardNumber.length() - 4));
    }
}

public class PayPalPayment implements PaymentStrategy {
    private String email;

    public PayPalPayment(String email) {
        this.email = email;
    }

    @Override
    public void pay(double amount) {
        System.out.println("Paid $" + amount + " using PayPal account: " + email);
    }
}
```
```Java
public class Order {
    private double totalAmount;
    private PaymentStrategy paymentStrategy;

    public Order(double totalAmount) {
        this.totalAmount = totalAmount;
    }

    // Allows dynamic runtime switching of strategies
    public void setPaymentStrategy(PaymentStrategy paymentStrategy) {
        this.paymentStrategy = paymentStrategy;
    }

    public void processPayment() {
        if (paymentStrategy == null) {
            throw new IllegalStateException("Payment strategy is not set.");
        }
        paymentStrategy.pay(totalAmount);
    }
}
```
```Java
public class Main {
    public static void main(String[] args) {
        Order order = new Order(150.50);

        // Pay using Credit Card
        order.setPaymentStrategy(new CreditCardPayment("1234567890123456"));
        order.processPayment();

        // Dynamically switch to PayPal at runtime
        order.setPaymentStrategy(new PayPalPayment("user@example.com"));
        order.processPayment();
    }
}
```


# Benefits of Using `Callable` Instead of Just an `int`

## What You're Implementing

This is the **Strategy Pattern** + **Higher-Order Functions** — passing *behavior* instead of *data*.

```python
async def _fallback_loop(
    self,
    messages: LanguageModelInput,
    start: int,
    get_target: Callable[[int], Any],       # HOW to get the target
    advance: Callable[[int], Optional[int]], # HOW to move forward
)
```

---

## ❌ Using Just an `int` (Limited Approach)

```python
async def _fallback_loop(self, messages, start: int, target: int, step: int):
    current = start
    while current < target:
        result = self._try_something(current)
        if not result:
            break
        current += step  # rigid, always same behavior
```

**Problems:**
- Advancement logic is **hardcoded** (always `+= step`)
- Target is **fixed** — can't change based on state
- Can't handle **non-linear** flows
- Must rewrite the method for different behaviors

---

## ✅ Using `Callable` (Flexible Approach)

```python
# Default behaviors
def _default_target(index: int) -> Any:
    return self.models[index]

def _default_advance(index: int) -> Optional[int]:
    next_index = index + 1
    return next_index if next_index < len(self.models) else None

# Usage
await self._fallback_loop(messages, start, get_target, advance)
```

---

## Key Benefits

### 1. 🔄 **Behavior Can Change Dynamically**
```python
# Normal: go 1 by 1
def advance_sequential(i): return i + 1

# Skip every other model
def advance_skip(i): return i + 2

# Retry same index on failure
def advance_retry(i): return i if self.should_retry else i + 1

# Same loop, DIFFERENT behaviors
await self._fallback_loop(messages, 0, get_target, advance_sequential)
await self._fallback_loop(messages, 0, get_target, advance_skip)
await self._fallback_loop(messages, 0, get_target, advance_retry)
```

### 2. 🎯 **Target Can Be Complex Logic**
```python
# With int: target is always fixed
target = 5  # boring

# With Callable: target depends on state/context
def get_target(index: int):
    if self.is_premium_user:
        return self.premium_models[index]
    elif self.fallback_triggered:
        return self.fallback_models[index]
    else:
        return self.default_models[index]
```

### 3. 🧪 **Easy to Test**
```python
# Inject mock callables for testing
mock_get_target = lambda i: "mock_model"
mock_advance = lambda i: None  # stop after one iteration

await self._fallback_loop(messages, 0, mock_get_target, mock_advance)
# No need to set up real models!
```

### 4. 🔒 **Open/Closed Principle**
```python
# Loop logic NEVER changes
async def _fallback_loop(self, messages, start, get_target, advance):
    current = start
    while current is not None:
        target = get_target(current)  # delegate
        success = await self._try(messages, target)
        if success:
            break
        current = advance(current)    # delegate

# You ADD new behavior without MODIFYING the loop
```

### 5. ♻️ **Reusability**
```python
# Same loop for completely different use cases
await self._fallback_loop(messages, 0, get_model, advance_by_priority)
await self._fallback_loop(messages, 0, get_endpoint, advance_by_region)
await self._fallback_loop(messages, 0, get_provider, advance_by_cost)
```

---

## Summary

| | `int` only | `Callable` |
|---|---|---|
| Logic flexibility | ❌ Rigid | ✅ Dynamic |
| Non-linear flow | ❌ Hard | ✅ Easy |
| Testability | ❌ Hard to mock | ✅ Inject mocks |
| Reusability | ❌ Limited | ✅ High |
| Adding new behavior | ❌ Modify loop | ✅ New function |

> **Core idea:** Pass **what to do** (`Callable`) instead of **what value to use** (`int`), so the loop stays stable while behavior changes freely.



## note 4 More on callable 
**A callable is any object that can be called using parentheses () (like a function call).**

## Note 5, __all__
Controls what to export.\
when use import *, it **only import** the one defined in __all__.\
If no __all__ is being defined, it will import **all method not start with _**
```python
__all__ = ["LLMRegistry", "LLMService", "llm_service"]
```
