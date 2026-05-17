"""
RiskBudgetBuilder — traduce el perfil aprobado en un RiskBudget cuantitativo.

INVARIANTES de diseño:
    - El budget surge del approved_profile, NO del preliminary_profile.
    - risk_need NO eleva el perfil ni modifica el budget.
    - declared_return_expectation_pct NO interviene.
    - El horizonte y la liquidez pueden hacer el budget más conservador.
    - La experiencia inversora puede limitar productos complejos.
    - No se calculan retornos esperados acá.
    - No se construyen portfolios acá.

El builder es DETERMINISTA. Mismo input → mismo output. Sin IA.
"""

from typing import Any

from risk_first_advisory.kyc.models import FinancialGoal, KYCData
from risk_first_advisory.models.risk_budget import RiskBudget

# Parámetros base por perfil. Configuración en código por simplicidad de M1;
# en producción esto vive en config/profiles_params.yaml.
PROFILE_BASE_PARAMS: dict[str, dict[str, Any]] = {
    "conservador": {
        "target_volatility": 0.035,
        "max_volatility": 0.050,
        "max_drawdown": -0.070,
        "max_equity": 0.10,
        "max_high_yield": 0.00,
        "max_single_asset": 0.15,
        "max_sector_exposure": 0.20,
        "max_duration": 2.0,
        "complex_products_allowed": False,
    },
    "moderado-defensivo": {
        "target_volatility": 0.055,
        "max_volatility": 0.075,
        "max_drawdown": -0.100,
        "max_equity": 0.25,
        "max_high_yield": 0.05,
        "max_single_asset": 0.15,
        "max_sector_exposure": 0.25,
        "max_duration": 3.5,
        "complex_products_allowed": False,
    },
    "moderado": {
        "target_volatility": 0.075,
        "max_volatility": 0.100,
        "max_drawdown": -0.150,
        "max_equity": 0.40,
        "max_high_yield": 0.10,
        "max_single_asset": 0.15,
        "max_sector_exposure": 0.30,
        "max_duration": 5.0,
        "complex_products_allowed": False,
    },
    "moderado-agresivo": {
        "target_volatility": 0.105,
        "max_volatility": 0.140,
        "max_drawdown": -0.220,
        "max_equity": 0.60,
        "max_high_yield": 0.15,
        "max_single_asset": 0.20,
        "max_sector_exposure": 0.35,
        "max_duration": 7.0,
        "complex_products_allowed": True,
    },
    "agresivo": {
        "target_volatility": 0.140,
        "max_volatility": 0.200,
        "max_drawdown": -0.300,
        "max_equity": 0.80,
        "max_high_yield": 0.25,
        "max_single_asset": 0.25,
        "max_sector_exposure": 0.40,
        "max_duration": 10.0,
        "complex_products_allowed": True,
    },
}


VALID_PROFILES = frozenset(PROFILE_BASE_PARAMS.keys())


class RiskBudgetBuilder:
    """
    Construye un RiskBudget a partir del perfil aprobado, KYC y FinancialGoal.

    El método principal `build` aplica primero los parámetros base del perfil,
    luego una secuencia de reglas de ajuste que pueden hacer el budget MÁS
    conservador (nunca más permisivo).
    """

    def build(
        self,
        approved_profile_name: str,
        kyc: KYCData,
        goal: FinancialGoal,
    ) -> RiskBudget:
        if not approved_profile_name or not approved_profile_name.strip():
            raise ValueError("approved_profile_name no puede estar vacío.")

        normalized = approved_profile_name.strip()
        if normalized not in VALID_PROFILES:
            raise ValueError(
                f"approved_profile_name desconocido: {approved_profile_name!r}. "
                f"Opciones válidas: {sorted(VALID_PROFILES)}."
            )

        params = dict(PROFILE_BASE_PARAMS[normalized])  # copia mutable
        notes: list[str] = []

        # ── Construcción inicial desde parámetros base ───────────────────
        budget_state: dict[str, Any] = {
            "profile_name": normalized,
            "target_volatility": params["target_volatility"],
            "max_volatility": params["max_volatility"],
            "max_drawdown": params["max_drawdown"],
            "min_liquidity": 0.0,
            "max_equity": params["max_equity"],
            "max_high_yield": params["max_high_yield"],
            "max_single_asset": params["max_single_asset"],
            "max_sector_exposure": params["max_sector_exposure"],
            "max_duration": params["max_duration"],
            "complex_products_allowed": params["complex_products_allowed"],
            "preferred_currency": kyc.preferred_currency,
        }

        # ── Regla 1: liquidez mínima desde KYC ──────────────────────────
        budget_state["min_liquidity"] = max(
            budget_state["min_liquidity"],
            kyc.liquidity_need_pct,
        )
        if kyc.liquidity_need_pct > 0.0:
            notes.append(
                f"min_liquidity ajustado a {kyc.liquidity_need_pct:.2%} "
                f"según necesidad de liquidez declarada en KYC."
            )

        # ── Regla 2: horizonte corto (<2 años) ──────────────────────────
        if goal.horizon_years < 2:
            if budget_state["max_equity"] > 0.15:
                budget_state["max_equity"] = 0.15
                notes.append(
                    f"max_equity recortado a 15% por horizonte corto ({goal.horizon_years} años)."
                )
            if budget_state["max_duration"] > 2.0:
                budget_state["max_duration"] = 2.0
                notes.append(
                    f"max_duration recortado a 2.0 años por horizonte corto ({goal.horizon_years} años)."
                )

        # ── Regla 3: horizonte medio (2–5 años) ─────────────────────────
        elif 2 <= goal.horizon_years <= 5:
            if budget_state["max_duration"] > float(goal.horizon_years):
                budget_state["max_duration"] = float(goal.horizon_years)
                notes.append(
                    f"max_duration recortado a {goal.horizon_years} años para "
                    "alinearlo con el horizonte del objetivo."
                )

        # ── Regla 4: experiencia básica ─────────────────────────────────
        if kyc.experience.value == "basica":
            if budget_state["complex_products_allowed"]:
                budget_state["complex_products_allowed"] = False
                notes.append(
                    "complex_products_allowed = false porque la experiencia inversora "
                    "declarada es 'basica'."
                )
            if budget_state["max_single_asset"] > 0.15:
                budget_state["max_single_asset"] = 0.15
                notes.append("max_single_asset recortado a 15% por experiencia inversora 'basica'.")

        # ── Regla 5: preferencia por productos simples ──────────────────
        if kyc.prefers_simple_products and budget_state["complex_products_allowed"]:
            budget_state["complex_products_allowed"] = False
            notes.append(
                "complex_products_allowed = false porque el cliente declara preferencia "
                "por instrumentos simples."
            )

        # ── Regla 6: capacidad financiera de pérdida menor al drawdown ──
        cap_drawdown_limit = -kyc.financial_loss_capacity_pct / 100.0
        base_drawdown = budget_state["max_drawdown"]
        if cap_drawdown_limit > base_drawdown:
            self._apply_drawdown_restriction(
                budget_state=budget_state,
                new_drawdown=cap_drawdown_limit,
                base_drawdown=params["max_drawdown"],
                notes=notes,
                reason=(
                    f"max_drawdown ajustado a {cap_drawdown_limit:.2%} porque la capacidad "
                    f"financiera de pérdida del cliente ({kyc.financial_loss_capacity_pct:.1f}%) "
                    "es menor al drawdown base del perfil."
                ),
            )

        # ── Regla 7: tolerancia emocional menor al drawdown ─────────────
        # Aplica sobre el estado actualizado (puede ya haber sido recortado por capacidad).
        tol_drawdown_limit = -kyc.emotional_loss_tolerance_pct / 100.0
        current_drawdown = budget_state["max_drawdown"]
        if tol_drawdown_limit > current_drawdown:
            self._apply_drawdown_restriction(
                budget_state=budget_state,
                new_drawdown=tol_drawdown_limit,
                base_drawdown=params["max_drawdown"],
                notes=notes,
                reason=(
                    f"max_drawdown ajustado a {tol_drawdown_limit:.2%} porque la tolerancia "
                    f"emocional del cliente ({kyc.emotional_loss_tolerance_pct:.1f}%) es menor "
                    "al drawdown previo."
                ),
            )

        # ── Construcción final del dataclass ────────────────────────────
        return RiskBudget(
            profile_name=budget_state["profile_name"],
            target_volatility=budget_state["target_volatility"],
            max_volatility=budget_state["max_volatility"],
            max_drawdown=budget_state["max_drawdown"],
            min_liquidity=budget_state["min_liquidity"],
            max_equity=budget_state["max_equity"],
            max_high_yield=budget_state["max_high_yield"],
            max_single_asset=budget_state["max_single_asset"],
            max_sector_exposure=budget_state["max_sector_exposure"],
            max_duration=budget_state["max_duration"],
            complex_products_allowed=budget_state["complex_products_allowed"],
            preferred_currency=budget_state["preferred_currency"],
            notes=notes,
        )

    @staticmethod
    def _apply_drawdown_restriction(
        budget_state: dict[str, Any],
        new_drawdown: float,
        base_drawdown: float,
        notes: list[str],
        reason: str,
    ) -> None:
        """
        Aplica una restricción de drawdown más conservadora.

        Reduce proporcionalmente target_volatility y max_volatility según la
        razón entre el nuevo drawdown y el base del perfil. El factor de
        reducción se calcula sobre el drawdown BASE del perfil, no sobre el
        drawdown actual del budget_state — esto evita compounding cuando
        capacidad y tolerancia aplican consecutivamente.
        """
        if base_drawdown >= 0:
            # No tiene sentido escalar — el base era 0 o positivo. Imposible
            # por construcción de los parámetros, pero defendemos el caso.
            scale_factor = 1.0
        else:
            scale_factor = abs(new_drawdown) / abs(base_drawdown)
            # Solo escalar hacia abajo, nunca hacia arriba
            scale_factor = min(scale_factor, 1.0)

        # Si el scale_factor es 1.0, no hay nada que escalar (no debería
        # llegar acá si la regla disparó, pero defendemos).
        if scale_factor < 1.0:
            base_target_vol = PROFILE_BASE_PARAMS[budget_state["profile_name"]]["target_volatility"]
            base_max_vol = PROFILE_BASE_PARAMS[budget_state["profile_name"]]["max_volatility"]

            new_target_vol = base_target_vol * scale_factor
            new_max_vol = base_max_vol * scale_factor

            # Solo aplicar si reduce respecto al estado actual.
            if new_target_vol < budget_state["target_volatility"]:
                budget_state["target_volatility"] = new_target_vol
            if new_max_vol < budget_state["max_volatility"]:
                budget_state["max_volatility"] = new_max_vol

        budget_state["max_drawdown"] = new_drawdown
        notes.append(reason)
        notes.append(
            f"target_volatility y max_volatility reducidos proporcionalmente "
            f"(factor {scale_factor:.3f})."
        )
