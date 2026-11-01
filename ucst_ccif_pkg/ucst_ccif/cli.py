"""
ucst-ccif command-line interface.

Usage:
    ucst-ccif run         Run the continuum model with synthetic forcing
    ucst-ccif audit       Run leakage audit on a CSV
    ucst-ccif compare     Run M0 vs M1 comparison on a CSV
    ucst-ccif version     Print version
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from . import __version__
from .compartments import CarbonContinuumModel
from .parameters import ParameterSet, draw_parameters
from .uncertainty import MonteCarloEnsemble
from .leakage import audit_leakage
from .models import compare_m0_m1
from .rothc_lite import run_rothc, run_rothc_dataframe
from .bluecarbon_lookups import blue_carbon_estimate
from .dndc_lite import rice_ch4_season
from .threepg_lookups import get_species
from .raymond_evasion import EvasionKernel
from .netcdf_priors import list_sources, PriorClient


def _cmd_run(args) -> int:
    T = 365
    doy = np.arange(T)
    gpp = np.clip(3.5 + 2.5 * np.sin(2*np.pi*(doy - 105)/365.25), 0.2, 7.0)
    T_air = 18.0 + 12.0 * np.sin(2*np.pi*(doy - 200)/365.25)
    swc = np.clip(0.55 + 0.15 * np.sin(2*np.pi*(doy - 30)/365.25), 0.2, 0.9)
    rain = np.where(np.random.default_rng(0).random(T) < 0.15, 5.0, 0.0)

    if args.mc:
        mc = MonteCarloEnsemble(n_members=args.mc)
        out = mc.run(gpp, T_air, swc, rain)
        print(f"Annual NEE mean: {out['nee_mean'].mean()*365:+.1f} gC m-2 yr-1")
        print(f"90% interval:    [{out['nee_p5'].mean()*365:+.1f}, {out['nee_p95'].mean()*365:+.1f}]")
    else:
        model = CarbonContinuumModel(ParameterSet())
        state = model.run(gpp, T_air, swc, rain)
        print(f"Annual NEE:      {state.nee.mean()*365:+.1f} gC m-2 yr-1")
        print(f"Mean |eps_C|:    {np.mean(np.abs(state.eps_C)):.4f}")
    return 0


def _cmd_audit(args) -> int:
    df = pd.read_csv(args.csv)
    predictors = [c for c in df.columns
                  if c != args.target and pd.api.types.is_numeric_dtype(df[c])]
    report = audit_leakage(df, args.target, predictors)
    print(report.summary())
    return 0


def _cmd_compare(args) -> int:
    df = pd.read_csv(args.csv)
    exo = [c for c in args.exo.split(",")
           if pd.api.types.is_numeric_dtype(df[c])]
    results = compare_m0_m1(df, args.target, exo,
                            calib_end_year=args.calib_end)
    for name, r in results.items():
        print(f"{name}: valid RMSE={r.valid_rmse:.4f}, R2={r.valid_r2:.4f}, "
              f"n_params={r.n_params}")
    return 0


def _cmd_rothc(args) -> int:
    import pandas as pd
    df = pd.read_csv(args.csv)
    r = run_rothc_dataframe(df, dpm_rpm=args.split)
    print(f"RothC-lite: {len(r.c_inputs)} months, "
          f"final SOC = {r.total_soc[-1]:.1f} tC/ha, "
          f"cum CO2 = {r.co2_flux.sum():.1f} tC/ha, "
          f"mean |residual| = {np.mean(np.abs(r.residual)):.2e}")
    return 0


def _cmd_blue(args) -> int:
    est = blue_carbon_estimate(args.ecosystem, args.region, area_ha=args.area)
    print(f"{est.ecosystem} ({est.region})")
    print(f"  C stock      : {est.stock_MgC_ha:.0f} Mg C/ha "
          f"(agb {est.agb_MgC_ha:.0f} + bgb {est.bgb_MgC_ha:.0f} + soil {est.soil_MgC_ha:.0f})")
    print(f"  Burial       : {est.burial_MgC_ha_yr:.1f} Mg C/ha/yr "
          f"({est.sequestration_gC_m2_yr:.0f} gC/m2/yr)")
    print(f"  CH4 CO2e     : {est.ch4_co2e_gCO2e_m2_yr:.2f} gCO2e/m2/yr")
    if args.area:
        print(f"  Project ({args.area:.0f} ha): "
              f"{est.total_stock_MgC:.0f} Mg C stock, "
              f"{est.annual_burial_MgC:.0f} Mg C/yr burial, "
              f"{est.annual_ch4_co2e_tCO2e:.1f} tCO2e/yr CH4")
    return 0


def _cmd_rice(args) -> int:
    est = rice_ch4_season(args.regime, args.days, area_ha=args.area,
                          organic_amendment=args.amendment,
                          cultivar_factor=args.cultivar)
    print(f"Rice CH4 ({est.water_regime}, {est.days} d): "
          f"{est.adjusted_kgCH4_ha:.1f} kg CH4/ha/season "
          f"= {est.co2e_tCO2e_ha:.2f} tCO2e/ha/season "
          f"(SFw {est.sfw:.2f} x SFp {est.sfp:.2f} x SFo {est.sfo:.2f})")
    if args.area:
        print(f"  Total: {est.total_kgCH4:.1f} kg CH4, "
              f"{est.total_tCO2e:.2f} tCO2e")
    return 0


def _cmd_evasion(args) -> int:
    k = EvasionKernel(water_type=args.water_type,
                      velocity=args.velocity, slope=args.slope)
    flux = k.flux_gC_m2_d(args.pco2, args.temp)
    print(f"Evasion ({args.water_type}): k600 = {k.k600():.3f} m/d, "
          f"flux = {flux:.2f} gC/m2/d "
          f"({flux*365/1000:.2f} kgC/m2/yr) at pCO2={args.pco2} uatm, T={args.temp}C")
    return 0


def _cmd_priors(args) -> int:
    if args.list:
        for s in list_sources():
            print(f"  {s}")
        return 0
    client = PriorClient()
    try:
        client.fetch(args.source)
    except NotImplementedError as e:
        print(f"[{args.source}] ETL not wired: {e}")
    except ImportError as e:
        print(f"[{args.source}] dependency missing: {e}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ucst-ccif",
                                     description="UCST-CCIF carbon flux toolkit")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run continuum model")
    p_run.add_argument("--mc", type=int, default=0, help="Monte Carlo members")
    p_run.set_defaults(func=_cmd_run)

    p_aud = sub.add_parser("audit", help="Leakage audit on CSV")
    p_aud.add_argument("--csv", required=True)
    p_aud.add_argument("--target", default="NEE_daily_total")
    p_aud.set_defaults(func=_cmd_audit)

    p_cmp = sub.add_parser("compare", help="M0 vs M1 comparison")
    p_cmp.add_argument("--csv", required=True)
    p_cmp.add_argument("--target", default="NEE_daily_total")
    p_cmp.add_argument("--exo", required=True, help="comma-separated exogenous cols")
    p_cmp.add_argument("--calib-end", type=int, default=2020)
    p_cmp.set_defaults(func=_cmd_compare)

    p_rothc = sub.add_parser("rothc", help="Run RothC-lite on a CSV")
    p_rothc.add_argument("--csv", required=True,
                         help="cols: c_inputs, T, smd, tsd [, cover, clay_pct]")
    p_rothc.add_argument("--split", default="crop",
                         help="DPM:RPM split key or ratio (default crop)")
    p_rothc.set_defaults(func=_cmd_rothc)

    p_blue = sub.add_parser("blue", help="Blue-carbon lookup")
    p_blue.add_argument("--ecosystem", required=True,
                        choices=["mangrove", "saltmarsh", "seagrass"])
    p_blue.add_argument("--region", default="subtropical")
    p_blue.add_argument("--area", type=float, default=0.0, help="project area ha")
    p_blue.set_defaults(func=_cmd_blue)

    p_rice = sub.add_parser("rice", help="Rice CH4 Tier-1 (DNDC-lite)")
    p_rice.add_argument("--regime", required=True)
    p_rice.add_argument("--days", type=int, required=True)
    p_rice.add_argument("--amendment", default="none")
    p_rice.add_argument("--cultivar", type=float, default=1.0)
    p_rice.add_argument("--area", type=float, default=1.0)
    p_rice.set_defaults(func=_cmd_rice)

    p_ev = sub.add_parser("evasion", help="Inland-water CO2 evasion (Raymond-2013)")
    p_ev.add_argument("--water-type", default="stream", choices=["stream", "lake"])
    p_ev.add_argument("--pco2", type=float, default=1500.0, help="water pCO2 uatm")
    p_ev.add_argument("--temp", type=float, default=20.0)
    p_ev.add_argument("--velocity", type=float, default=0.5)
    p_ev.add_argument("--slope", type=float, default=0.001)
    p_ev.set_defaults(func=_cmd_evasion)

    p_pri = sub.add_parser("priors", help="Prior sources registry")
    p_pri.add_argument("--list", action="store_true", help="list sources")
    p_pri.add_argument("--source", default=None)
    p_pri.set_defaults(func=_cmd_priors)

    sub.add_parser("version").set_defaults(
        func=lambda a: (print(f"ucst-ccif {__version__}"), 0)[1])

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
