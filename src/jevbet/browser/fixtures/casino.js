/* Jevbet local mock casino. No network. No real-money accounting. */
(function () {
  "use strict";

  var table = document.getElementById("table");
  if (!table) return;

  var game = table.dataset.game;
  var params = new URLSearchParams(location.search);
  var RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];
  var SUITS = ["S", "H", "D", "C"];
  var LABELS = {
    hit: "Hit",
    stand: "Stand",
    double: "Double",
    split: "Split",
    fold: "Fold",
    check: "Check",
    call: "Call",
    raise: "Raise",
    deal: "Deal",
  };

  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0;
      a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  var rand = mulberry32(Number(params.get("seed") || "7") || 7);
  var shoe = [];

  function reshuffle() {
    shoe = [];
    var d, r, s, i, j;
    for (d = 0; d < 4; d += 1) {
      for (r = 0; r < RANKS.length; r += 1) {
        for (s = 0; s < SUITS.length; s += 1) shoe.push(RANKS[r] + SUITS[s]);
      }
    }
    for (i = shoe.length - 1; i > 0; i -= 1) {
      j = Math.floor(rand() * (i + 1));
      var tmp = shoe[i];
      shoe[i] = shoe[j];
      shoe[j] = tmp;
    }
  }

  function draw() {
    if (!shoe.length) reshuffle();
    return shoe.pop();
  }

  function rankOf(label) {
    return label.slice(0, -1);
  }

  function handTotal(cards) {
    var total = 0;
    var aces = 0;
    var i, r;
    for (i = 0; i < cards.length; i += 1) {
      r = rankOf(cards[i]);
      if (r === "A") {
        aces += 1;
        total += 11;
      } else if (r === "10" || r === "J" || r === "Q" || r === "K") total += 10;
      else total += Number(r);
    }
    var softAces = aces;
    while (total > 21 && softAces) {
      total -= 10;
      softAces -= 1;
    }
    return { total: total, soft: softAces > 0 };
  }

  function parseList(raw) {
    return String(raw || "")
      .split(/[,\s]+/)
      .map(function (part) {
        return part.trim().toUpperCase();
      })
      .filter(Boolean);
  }

  function round2(value) {
    return Math.round(value * 100) / 100;
  }

  function cardHTML(label) {
    if (!label || label === "??") return '<span class="card back" aria-hidden="true"></span>';
    var suit = label.slice(-1);
    var red = suit === "H" || suit === "D";
    var glyph = { S: "♠", H: "♥", D: "♦", C: "♣" }[suit] || suit;
    return (
      '<span class="card' +
      (red ? " red" : "") +
      '"><span>' +
      rankOf(label) +
      '</span><span>' +
      glyph +
      "</span></span>"
    );
  }

  var cash = Number(params.get("bankroll") || table.dataset.bankroll || "500");
  var profit = Number(params.get("session_profit") || table.dataset.sessionProfit || "0");
  var currency = table.dataset.currency || "EUR";
  var baseBet = Number(params.get("bet") || table.dataset.bet || "25");
  var phase = table.dataset.phase || "playing";
  if (params.get("stop_loss")) table.dataset.stopLoss = params.get("stop_loss");

  var playerHands = [];
  var bets = [];
  var active = 0;
  var dealer = [];
  var hole = [];
  var board = [];
  var pot = Number(table.dataset.pot || "0");
  var toCall = Number(table.dataset.toCall || "0");
  var minRaise = Number(table.dataset.minRaise || "0");

  if (game === "blackjack") {
    var playerEl = table.querySelector("[data-role=player]");
    var dealerEl = table.querySelector("[data-role=dealer]");
    playerHands = [parseList(playerEl && playerEl.dataset.cards)];
    bets = [Number(table.dataset.bet || baseBet)];
    dealer = [
      ((dealerEl && dealerEl.dataset.upcard) || "KH").toUpperCase(),
      ((dealerEl && dealerEl.dataset.hole) || "3C").toUpperCase(),
    ];
  } else {
    var heroEl = table.querySelector("[data-role=hero]");
    var boardEl = table.querySelector("[data-role=board]");
    hole = parseList(heroEl && heroEl.dataset.cards);
    board = parseList(boardEl && boardEl.dataset.cards);
  }

  function paintMoney() {
    var bankroll = document.getElementById("bankroll-display");
    var profitEl = document.getElementById("profit-display");
    if (bankroll) bankroll.textContent = String(round2(cash));
    if (profitEl) profitEl.textContent = String(round2(profit));
    table.dataset.bankroll = String(round2(cash));
    table.dataset.sessionProfit = String(round2(profit));
    table.dataset.currency = currency;
    table.dataset.phase = phase;
  }

  function renderActions(actions) {
    var host = document.getElementById("actions");
    host.innerHTML = actions
      .map(function (action) {
        return '<button type="button" data-action="' + action + '">' + (LABELS[action] || action) + "</button>";
      })
      .join("");
    if (game === "holdem" && actions.indexOf("raise") !== -1) {
      host.insertAdjacentHTML(
        "beforeend",
        '<label class="stake">Amount <input data-amount type="number" min="' +
          minRaise +
          '" step="1" value="' +
          minRaise +
          '" /></label>'
      );
    }
  }

  function setStatus(text) {
    var status = document.getElementById("status");
    if (status) status.textContent = text;
  }

  function legalBlackjack() {
    if (phase !== "playing") return ["deal"];
    var hand = playerHands[active];
    var actions = ["hit", "stand"];
    if (hand.length === 2 && cash + 1e-9 >= bets[active]) {
      actions.push("double");
      if (playerHands.length === 1 && rankOf(hand[0]) === rankOf(hand[1])) actions.push("split");
    }
    return actions;
  }

  function renderBlackjack() {
    var shown = phase === "playing" ? [dealer[0], "??"] : dealer.slice();
    dealerEl.dataset.upcard = dealer[0];
    dealerEl.dataset.hole = dealer[1] || "";
    dealerEl.innerHTML = "<p>Dealer</p><div class=\"cards\">" + shown.map(cardHTML).join("") + "</div>";
    var hand = playerHands[active] || [];
    var info = handTotal(hand);
    playerEl.dataset.cards = hand.join(",");
    playerEl.dataset.soft = info.soft ? "true" : "false";
    playerEl.innerHTML =
      "<p>You</p>" +
      playerHands
        .map(function (cards, index) {
          var mark = index === active && phase === "playing" ? " active" : "";
          return '<div class="hand' + mark + '">' + cards.map(cardHTML).join("") + "</div>";
        })
        .join("");
    table.dataset.bet = String(bets[active] || baseBet);
    table.dataset.tableMin = String(baseBet);
    paintMoney();
    renderActions(legalBlackjack());
  }

  function finishBlackjackHand() {
    if (active + 1 < playerHands.length) {
      active += 1;
      renderBlackjack();
      return;
    }
    settleBlackjack();
  }

  function settleBlackjack() {
    var live = playerHands.some(function (hand) {
      return handTotal(hand).total <= 21;
    });
    var dealerNatural = handTotal(dealer.slice(0, 2)).total === 21;
    var guard = 0;
    if (live && !dealerNatural) {
      while (handTotal(dealer).total < 17 && guard < 12) {
        dealer.push(draw());
        guard += 1;
      }
    }
    var dealerTotal = handTotal(dealer).total;
    playerHands.forEach(function (hand, index) {
      var total = handTotal(hand).total;
      var bet = bets[index];
      var natural = playerHands.length === 1 && hand.length === 2 && total === 21;
      if (total > 21 || (dealerTotal <= 21 && total < dealerTotal)) {
        profit = round2(profit - bet);
        setStatus("Lost " + bet + ".");
      } else if (natural && !dealerNatural) {
        cash = round2(cash + bet * 2.5);
        profit = round2(profit + bet * 1.5);
        setStatus("Blackjack pays 3:2.");
      } else if (dealerTotal > 21 || total > dealerTotal) {
        cash = round2(cash + bet * 2);
        profit = round2(profit + bet);
        setStatus("Won " + bet + ".");
      } else {
        cash = round2(cash + bet);
        setStatus("Push.");
      }
    });
    phase = "between";
    renderBlackjack();
  }

  function dealBlackjack() {
    if (cash + 1e-9 < baseBet) {
      phase = "between";
      setStatus("Bankroll is below the table minimum.");
      renderBlackjack();
      return;
    }
    cash = round2(cash - baseBet);
    playerHands = [[draw(), draw()]];
    bets = [baseBet];
    active = 0;
    dealer = [draw(), draw()];
    phase = "playing";
    setStatus("New hand.");
    renderBlackjack();
  }

  function onBlackjack(action) {
    if (action === "deal") {
      dealBlackjack();
      return;
    }
    if (phase !== "playing") return;
    var hand = playerHands[active];
    if (action === "hit") {
      hand.push(draw());
      if (handTotal(hand).total > 21) finishBlackjackHand();
      else renderBlackjack();
      return;
    }
    if (action === "stand") {
      finishBlackjackHand();
      return;
    }
    if (action === "double") {
      var extra = bets[active];
      cash = round2(cash - extra);
      bets[active] = round2(extra * 2);
      hand.push(draw());
      finishBlackjackHand();
      return;
    }
    if (action === "split") {
      var stake = bets[0];
      cash = round2(cash - stake);
      playerHands = [
        [hand[0], draw()],
        [hand[1], draw()],
      ];
      bets = [stake, stake];
      active = 0;
      setStatus("Split.");
      renderBlackjack();
    }
  }

  function legalHoldem() {
    if (phase !== "playing") return ["deal"];
    var actions = ["fold"];
    if (toCall <= 1e-9) actions.push("check");
    else if (cash + 1e-9 >= toCall) actions.push("call");
    if (minRaise > 0 && cash + 1e-9 >= minRaise) actions.push("raise");
    return actions;
  }

  function renderHoldem() {
    boardEl.dataset.cards = board.join(",");
    heroEl.dataset.cards = hole.join(",");
    boardEl.innerHTML = "<p>Board</p><div class=\"cards\">" + board.map(cardHTML).join("") + "</div>";
    heroEl.innerHTML = "<p>You</p><div class=\"cards\">" + hole.map(cardHTML).join("") + "</div>";
    table.dataset.street = "flop";
    table.dataset.pot = String(pot);
    table.dataset.toCall = String(toCall);
    table.dataset.stack = String(round2(cash));
    table.dataset.minRaise = String(minRaise);
    table.dataset.raiseSuggestions = [minRaise, minRaise * 2, pot].filter(Boolean).join(",");
    table.dataset.tableMin = "0";
    paintMoney();
    renderActions(legalHoldem());
  }

  function dealHoldem() {
    hole = [draw(), draw()];
    board = [draw(), draw(), draw()];
    pot = 60;
    toCall = 20;
    minRaise = 20;
    phase = "playing";
    setStatus("New flop.");
    renderHoldem();
  }

  function finishHoldem(message) {
    phase = "between";
    setStatus(message);
    renderHoldem();
  }

  function onHoldem(action) {
    if (action === "deal") {
      dealHoldem();
      return;
    }
    if (phase !== "playing") return;
    if (action === "fold") {
      finishHoldem("Folded.");
      return;
    }
    if (action === "check") {
      finishHoldem("Checked.");
      return;
    }
    if (action === "call") {
      var pay = Math.min(toCall, cash);
      cash = round2(cash - pay);
      if (rand() < 0.45) {
        cash = round2(cash + pot + pay);
        profit = round2(profit + pot);
        finishHoldem("Called and won the pot.");
      } else {
        profit = round2(profit - pay);
        finishHoldem("Called and lost " + pay + ".");
      }
      return;
    }
    if (action === "raise") {
      var input = table.querySelector("input[data-amount]");
      var amount = input ? Number(input.value) : minRaise;
      if (!isFinite(amount) || amount < minRaise || amount > cash + 1e-9) {
        setStatus("Raise must be between " + minRaise + " and " + cash + ".");
        return;
      }
      cash = round2(cash - amount);
      if (rand() < 0.45) {
        cash = round2(cash + pot + amount + amount);
        profit = round2(profit + pot + amount);
        finishHoldem("Raised " + amount + " and won.");
      } else {
        profit = round2(profit - amount);
        finishHoldem("Raised " + amount + " and lost.");
      }
    }
  }

  table.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-action]");
    if (!button) return;
    if (game === "blackjack") onBlackjack(button.dataset.action);
    else onHoldem(button.dataset.action);
  });

  if (game === "blackjack") renderBlackjack();
  else renderHoldem();
})();
