"""refedge — NBA referee-crew edge research for total-points prediction markets.

Research goal (honest-backtest framing): quantify whether including referee-crew
features improves out-of-sample total-points prediction *over and above the market
line*, and whether any such improvement is large enough to overcome fees/spread.
A null result is a valid, reportable outcome. The entire design prioritises
avoiding look-ahead bias and overfitting over producing a large edge number.
"""

__version__ = "0.1.0"
