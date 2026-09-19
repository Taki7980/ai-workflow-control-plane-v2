from python.payments import execute_payment as charge


def process_order() -> int:
    return charge(10)
