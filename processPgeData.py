#!python
import csv
import sys
import argparse
import calendar
import datetime
import dateutil
from datetime import timedelta
import IPython
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
#from tkinter import Tk, Button, Toplevel, Label
#from tkinter import *
import tkinter
from tkcalendar import Calendar
from matplotlib.backend_bases import key_press_handler
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg, NavigationToolbar2Tk)

# Note: Look for PGE usage on day I shutoff our solar for the day.
# Should be around Dec 23, 2009
# Also look at impact after I washed solar panels 1/17/09

estYearlyPgeEscalation  = 0.06      # %
est2024PgeCost          = 5763.54   # Based on 2024 solar and usage using latest PGE E-TOU-D rate plan numbers
oldSolarYearlyProd      = 5732      # Based on 2024 solar production measured by our Emporia VUE system
nonExportLimit          = 5.0       # Based on rating of SMA 5000 Inverter used for NEM 1.0 application

# Minumum daily PGE charge if we don't use at least accrue at least that much in grid import charges
pgeMinDailyDeliveryCharge = 0.39167 # Dollars, approx $12 per month

vueDateLabel  = 'Time Bucket (America/Los_Angeles)'
vueSolarLabel = 'Main panel-Solar/Generation-Solar inverter (kWhs)'
pgeData = {}
vueData = {}

# PGE Baseline Info 2024
# https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html#tabs-59f0a2f599-item-f6f6231a48-tab
BaselineTerritory = 'X'     # Our territory from PGE bill
BaselineSummer    = 9.8     # kWh/day
BaselineWinter    = 9.7     # kWh/day

# PGE Rate Data 2024
# https://www.pge.com/assets/pge/docs/account/rate-plans/residential-electric-rate-plan-pricing.pdf
RatePlans = {
    "E-TOU-C": {
        "Summer": {
            "Baseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                },
            "AboveBaseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                }
            },
        "Winter": {
            "Baseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                },
            "AboveBaseline": {
                "OffPeak":  0.40,
                "Peak":     0.51
                }
            }
        },
    "E-TOU-D": {
        "Summer": {
            "OffPeak":  0.43,
            "Peak":     0.57
            },
        "Winter": {
            "OffPeak":  0.44,
            "Peak":     0.48
            }
        },
    "E-ELEC": {
        "Summer": {
            "OffPeak":      0.40,
            "PartialPeak":  0.45,
            "Peak":         0.62
            },
        "Winter": {
            "OffPeak":      0.35,
            "PartialPeak":  0.36,
            "Peak":         0.38
            }
        }
    }

SelectedDay = None
root = None
matplotlib.use('TkAgg')

def select_date():
    def on_date_select(date):
        global SelectedDay
        SelectedDay = date
        print( f"SelectedDay={SelectedDay:%b %d, %Y}" )
        #ax.set_xlim(date, date + datetime.timedelta(days=1))
        myHomeSolar.PlotOptions()
        #plt.draw()
        top.destroy()

    #global root, myHomeSolar
    global SelectedDay, myHomeSolar
    top = tkinter.Toplevel(myHomeSolar)
    #top = tkinter.Toplevel(myHomeSolar)
    cal = Calendar(top, selectmode='day', date_pattern='yyyy-mm-dd',
                    year=SelectedDay.year, month=SelectedDay.month, day=SelectedDay.day)
    cal.pack()
    tkinter.Button(top, text="Select", command=lambda: on_date_select(cal.selection_get())).pack()

def isPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak
        if timeOfDay.weekday() >= 5:
            return False
        if timeOfDay.hour < 17 or timeOfDay.hour >= 20:
            return False
        return True
    # Other rate plans have peak hours 4pm to 9pm
    if timeOfDay.hour < 16 or timeOfDay.hour >= 21:
        return False
    return True

def isPartialPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-ELEC':
        # E-ELEC Partial Peak Every day 3pm-4pm and 9pm to midnight
        if timeOfDay.hour == 15 or timeOfDay.hour >= 21:
            return True
        return False
    return False

def isOffPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-D' )
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-C' )
    if ratePlan == 'E-ELEC':
        # E-ELEC Off Peak Every day midnight to 3pm
        if timeOfDay.hour < 15:
            return True
        return False
    return False

class   HourlyData:
    def __init__( self ):
        self.Usage     = 0
        self.SolarProd = 0
        self.TimeOfDay = datetime.now()
    def __init__( self, usage, solarProd, timeOfDay ):
        self.Usage     = usage
        self.SolarProd = solarProd
        self.TimeOfDay = timeOfDay

def isSummerTime( timeOfDay ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return True
    return False

def isWinterTime( timeOfDay ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return True
    return False

def isSummerPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isSummerPartialPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPartialPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isSummerOffPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

def isWinterOffPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

# class HourlyProj
class   HourlyProj:
    """
    Used to compute hour by hour projections of grid vs solar vs battery status
    Includes usage, solar production, charging, export, excess solar, etc.
    """
    def __init__( self, time=None, grid=0, usage=0, battery=0, batteryUsed=0, charging=0, newSolar=0, oldSolar=0, newExcess=0, oldExcess=0, export=0, cost=0 ):
        # Keep these values as the input conditions
        self.TimeOfDay = datetime.datetime(year=2000,month=1,day=1) if time == None else time
        self.Usage     = usage     # kWh
        self.NewSolar  = newSolar  # kWh
        self.OldSolar  = oldSolar  # kWh
        # These values get revised as we do hourly processing
        self.Grid      = grid      # Grid import kWh
        self.Export    = export    # Grid Export kWh
        self.Battery   = battery   # Hourly Battery charge kWh
        self.BatteryUsed= batteryUsed # Battery used this hour kWh
        self.Charging  = charging  # Charging kWh
        self.NewExcess = newExcess # Excess New Solar kWh
        self.OldExcess = oldExcess # Excess Old Solar kWh
        self.Cost      = cost      # $

    def __str__( self ):
        #return f"{self.TimeOfDay}: Cost={self.Cost:>6.2f}, Grid={self.Grid:>6.2f}, Charging={self.Charging:>6.2f}, Battery={self.Battery:>6.2f}, Export={self.Export:>6.2f}" 
        return f"{self.TimeOfDay}: Usage={self.Usage:>6.2f}, NewSolar={self.NewSolar:>6.2f}, OldSolar={self.OldSolar:>6.2f}, Grid={self.Grid:>6.2f}, Export={self.Export:>6.2f}, Charging={self.Charging:>6.2f}, Battery={self.Battery:>6.2f}, BatteryUsed={self.BatteryUsed:>6.2f}, NewExcess={self.NewExcess:>6.2f}, OldExcess={self.OldExcess:>6.2f}, Cost=${self.Cost:>6.2f}"

    # Arithmetic operators
    def __add__( self, other ):
        # Note: Battery does not get added
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess,
                            newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid        += other.Grid
        result.Usage       += other.Usage
        result.Charging    += other.Charging
        result.NewExcess   += other.NewExcess
        result.OldExcess   += other.OldExcess
        result.NewSolar    += other.NewSolar
        result.OldSolar    += other.OldSolar
        result.Export      += other.Export
        result.BatteryUsed += other.BatteryUsed
        result.Cost        += other.Cost
        result.TimeOfDay    = max( result.TimeOfDay, other.TimeOfDay )
        return result
    def __truediv__( self, other ):
        # Note: Battery and TimeOfDay do not get modified
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess, newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid     /= other
        result.Usage    /= other
        result.Charging /= other
        result.NewExcess/= other
        result.OldExcess/= other
        result.NewSolar /= other
        result.OldSolar /= other
        result.Export   /= other
        result.BatteryUsed /= other
        result.Cost     /= other
        return result
    def __mul__( self, other ):
        # Note: Battery and TimeOfDay do not get modified
        result = HourlyProj( time=self.TimeOfDay, grid=self.Grid, usage=self.Usage, battery=self.Battery, charging=self.Charging,
                            newExcess=self.NewExcess, oldExcess=self.OldExcess, newSolar=self.NewSolar, oldSolar=self.OldSolar,
                            batteryUsed=self.BatteryUsed, export=self.Export, cost=self.Cost )
        result.Grid     *= other
        result.Usage    *= other
        result.Charging *= other
        result.NewExcess*= other
        result.OldExcess*= other
        result.NewSolar *= other
        result.OldSolar *= other
        result.Export   *= other
        result.BatteryUsed *= other
        result.Cost     *= other
        return result

    def ApplyBatteryToGrid( self ):
        if self.Grid > 0 and self.Battery > 0:
            if self.Battery >= self.Grid:
                self.BatteryUsed = self.Grid
                self.Battery -= self.BatteryUsed
                self.Grid = 0
            else:
                self.Grid -= self.Battery
                self.BatteryUsed = self.Battery
                self.Battery = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyNewSolarToBattery( self, options ):
        if self.NewExcess <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.NewExcess * options.Efficiency / 100
        newCharge = min( availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.NewExcess = max( 0, self.NewExcess - newCharge / (options.Efficiency/100) )
 
    def ApplyOldSolarToBattery( self, options ):
        if self.OldExcess <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.OldExcess * options.Efficiency / 100
        newCharge = min( availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.OldExcess = max( 0, self.OldExcess - newCharge / (options.Efficiency/100) )

    def ApplyOldSolarToGrid( self ):
        if self.Grid > 0 and self.OldExcess > 0:
            if self.OldExcess >= self.Grid:
                self.OldExcess -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.OldExcess
                self.OldExcess = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyNewSolarToGrid( self ):
        if self.Grid > 0 and self.NewExcess > 0:
            if self.NewExcess >= self.Grid:
                self.NewExcess -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.NewExcess
                self.NewExcess = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ExportBatteryToGrid( self, maxExport, options ):
        if self.Battery <= 0:
            return
        availExport = max( self.Battery, maxExport, options.MaxOutput )
        newExport = max( nonExportLimit, self.Export + availExport )
        self.BatteryUsed = newExport - self.Export
        self.Battery -= self.BatteryUsed
        self.Export = newExport
 
    def ExportNewSolarToGrid( self ):
        availExport = min( self.NewExcess, nonExportLimit - self.Export )
        if availExport > 0:
            self.Export    += availExport
            self.NewExcess -= availExport

    def ExportOldSolarToGrid( self ):
        availExport = min( self.OldExcess, nonExportLimit - self.Export )
        if availExport > 0:
            self.Export    += availExport
            self.OldExcess -= availExport

    def DetermineCost( self, options, dailyTotal=0 ):
        ratePlan = options.RatePlan
        if ratePlan not in RatePlans:
            print( "Error: Rate Plan %s not supported!" % ratePlan )
            return 0
        if self.Grid < 0:
            print( "Error: Negative grid usage must be applied as Export!" )
            return 0
        kWh = self.Grid
        if ratePlan == "E-TOU-C":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    # BaselineTotel = 9.8
                    # dailyTotal = 8.2
                    # kWh = 2.0
                    # 1.6 kWh @ baseline
                    # .4 kWh above baseline
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["Peak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["Peak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["Peak"]
            elif isSummerPartialPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["PartialPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["PartialPeak"]
            elif isWinterPartialPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["PartialPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["PartialPeak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                if BaselineSummer > dailyTotal:
                    baselineUsage = min(kWh, BaselineSummer-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Summer"]["Baseline"]["OffPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["AboveBaseline"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                if BaselineWinter > dailyTotal:
                    baselineUsage = min(kWh, BaselineWinter-dailyTotal)
                    self.Cost = baselineUsage * RatePlans[ratePlan]["Winter"]["Baseline"]["OffPeak"]
                    kWh = min(baselineUsage-kWh,0)
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["AboveBaseline"]["OffPeak"]
        elif ratePlan == "E-TOU-D":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["Peak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["OffPeak"]
        elif ratePlan == "E-ELEC":
            if isSummerPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["Peak"]
            elif isWinterPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["Peak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["Peak"]
            elif isSummerPartialPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["PartialPeak"]
            elif isWinterPartialPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["PartialPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["PartialPeak"]
            elif isSummerOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost = kWh * RatePlans[ratePlan]["Summer"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Summer"]["OffPeak"]
            elif isWinterOffPeakTime(self.TimeOfDay,ratePlan):
                self.Cost += kWh * RatePlans[ratePlan]["Winter"]["OffPeak"]
                if options.NEM == '1.0':
                    self.Cost -= self.Export * RatePlans[ratePlan]["Winter"]["OffPeak"]
        else:
            print( "Rate plan %s not supported!" % ratePlan )
        if options.NEM == '3.0':
            self.Cost -= self.Export * 0.06

#   Options for home solar projections
#   opt1 = Option( 'E-ELEC', '1.0', 13.5, 5600 )
class   Option( tkinter.Toplevel ):
    def __init__( self, parent, ratePlan, nem, maxBattery, newSolarProd, systemCost, efficiency=95 ):
        super().__init__(parent)
        self.RatePlan     = ratePlan      # 'E-ELEC' or 'E-TOU-C' or 'E-TOU-D'
        self.NEM          = nem           # '1.0' or '3.0'
        self.MaxBattery   = maxBattery    # kWh
        self.Efficiency   = efficiency    # %
        self.NewSolarProd = newSolarProd  # Yearly kWh
        self.SystemCost   = systemCost    # $
        self.YearlyPgeCost= 0             # $
        self.PaybackYears = 0             # years
        self.TwentyFiveYearSavings = 0    # $
        self.Projections   = []
        print( f"class Option: Created {self}" )
        # Set title, create figure and actors 
        plotTitle = f"RatePlan={self.RatePlan}, NEM={self.NEM}, MaxBattery={self.MaxBattery}, NewSolarProd={self.NewSolarProd}"
        self.title(plotTitle)
        self.fig = plt.figure( plotTitle, figsize=(15,6) )
        self.axs = self.fig.subplots( 1, 1 )
        #self.day_ax = self.axs[0]
        self.day_ax = self.axs
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)

    def __str__( self ):
        return f"RatePlan={self.RatePlan:>7}, NEM={self.NEM}, MaxBattery={self.MaxBattery}, Efficiency={self.Efficiency}, NewSolarProd={self.NewSolarProd}\nSystemCost=${self.SystemCost:>6.2f}, YearlyPgeCost=${self.YearlyPgeCost:>6.2f}, PaybackYears={self.PaybackYears:>3.1f} yrs, 25YearSavings=${self.TwentyFiveYearSavings:>8.2f}" 

    def ComputeYearlyCosts( self ):
        YearlyTotals = HourlyProj(battery=self.MaxBattery)
        for newHour in self.Projections:
            YearlyTotals = YearlyTotals + newHour
        self.YearlyPgeCost = YearlyTotals.Cost
        totalSavings = 0
        estFutureCostAsIs = est2024PgeCost
        estFutureCostOfOption = self.YearlyPgeCost
        for year in range(1,26):
            thisYearsSavings = estFutureCostAsIs - estFutureCostOfOption
            totalSavings += thisYearsSavings
            if self.PaybackYears == 0 and totalSavings >= self.SystemCost:
                self.PaybackYears = year + (1-(totalSavings-self.SystemCost)/thisYearsSavings)
            estFutureCostAsIs *= (1 + estYearlyPgeEscalation)
            estFutureCostOfOption *= (1 + estYearlyPgeEscalation)
        self.TwentyFiveYearSavings = totalSavings
        #print( f"Est Yearly PGE cost in 25 years={estFutureCostAsIs:$>6.2f}" )
        #print( f"Est Yearly Option cost in 25 years={estFutureCostOfOption:$>6.2f}" )

    def GetDataForDay( self, month, day ):
        Time = []
        Usage = []
        Solar = []
        Grid = []
        Export = []
        Battery = []
        batteryUsed = []
        Charging = []
        Excess = []
        Cost = []
        for hourlyData in self.Projections:
            if hourlyData.TimeOfDay.month != month:
                continue
            if hourlyData.TimeOfDay.day != day:
                continue
            if hourlyData.TimeOfDay.minute != 59:    # Computed hourlyData times end in *:59:59
                continue
            Time.append( hourlyData.TimeOfDay )
            Usage.append( hourlyData.Usage )
            Solar.append( hourlyData.NewSolar + hourlyData.OldSolar )
            Grid.append( hourlyData.Grid )
            Export.append( hourlyData.Export )
            Battery.append( hourlyData.Battery )
            batteryUsed.append( hourlyData.BatteryUsed )
            Charging.append( hourlyData.Charging / (self.Efficiency/100) )
            Excess.append( hourlyData.NewExcess + hourlyData.OldExcess )
            Cost.append( hourlyData.Cost )
        data = {    'TimeOfDay':    np.array(Time),
                    'Usage':        np.array(Usage),
                    'solar':        np.array(Solar),
                    'export':       np.array(Export),
                    'battery':      np.array(Battery),
                    'batteryUsed':  np.array(batteryUsed),
                    'charging':     np.array(Charging),
                    'excess':       np.array(Excess),
                    'cost':         np.array(Cost),
                    'grid':         np.array(Grid) }
        return data

    def PlotDay( self, month, day ):
        print( f"PlotDay: {month}/{day} for Option {self}" )
        data = self.GetDataForDay( month, day )
        print( "yticks range=", np.arange(int(max(data['solar'])+0.9)) )
        self.day_ax.set_yticks( np.arange(int(max(data['solar'])+0.9)) )
        self.day_ax.set_title(f"NewSolar={self.NewSolarProd}kWh, Battery={self.MaxBattery:.1f}kWh, Grid Usage Solar and Battery for {month}/{day}")
        self.day_ax.plot( 'TimeOfDay', 'Usage', data=data, color='xkcd:pale orange' )
        self.day_ax.plot( 'TimeOfDay', 'solar', data=data, color='xkcd:goldenrod', label='Solar Prod' )
        gridBottom = 'solar' + 'batteryUsed'
        self.day_ax.bar( 'TimeOfDay', 'grid', data=data, color='xkcd:orange', width=timedelta(minutes=20), align='center', label='Grid', bottom=gridBottom )
        self.day_ax.bar( 'TimeOfDay', 'solar', data=data, color='xkcd:goldenrod', width=timedelta(minutes=20), align='center', label='Solar' )
        #batteryBottom = data['Usage'] - data['batteryUsed']
        batteryBottom = 'solar'
        self.day_ax.bar( 'TimeOfDay', 'batteryUsed', data=data, color='xkcd:sky blue', width=timedelta(minutes=20), align='edge', label='Battery', bottom=batteryBottom)
        #chargingBottom = data['solar'] - data['batteryUsed']
        self.day_ax.bar( 'TimeOfDay', 'charging', data=data, color='xkcd:cobalt blue', width=timedelta(minutes=20), align='center', label='Charging', bottom='Usage' )
        exportBottom = data['solar'] - data['export']
        self.day_ax.bar( 'TimeOfDay', 'export', data=data, color='xkcd:fire engine red', width=timedelta(minutes=10), align='center', label='Export', bottom=exportBottom)
        self.day_ax.legend(loc='upper right')
        #self.canvas.draw()

    def PlotOption( self ):
        global SelectedDay, root, myHomeSolar
        print( f"PlotOption: {self}" )
        #self.fig.clf()
        self.day_ax.cla()
        #self.plotWindow = tkinter.Toplevel(root)
        self.day_ax.xaxis.set_major_locator(mdates.HourLocator())
        self.day_ax.xaxis.set_major_formatter(mdates.DateFormatter('%I%p'))
        #self.day_ax.set_xticks(rotation=45)
        self.day_ax.set_xlabel('Time')
        self.day_ax.set_ylabel('kWh')
 
        #button_ax = plt.axes([0.8, 0.05, 0.1, 0.075])
        #button = tkinter.Button(master=root, text='Select Date', command=select_date)
        #button = Button(button_ax, text='Select Date', color='xkcd:celery')
        self.toolbar.update()
        #button.pack()
        self.toolbar.pack(side=tkinter.BOTTOM, fill=tkinter.X)
        self.canvas.get_tk_widget().pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)

        # Plot data for selected day
        self.PlotDay( SelectedDay.month, SelectedDay.day )
        #self.plotWindow.grab_set()
        self.canvas.draw()

def DebugPeakVsOffPeakTimes( timeOfDay ):
    debugWinter2Summer = datetime.datetime( year=timeOfDay.year, month=6, day = 1 )
    debugSummer2Winter = datetime.datetime( year=timeOfDay.year, month=10, day = 1 )
    debugInterval = timedelta(days=1) 
    if (   abs(timeOfDay - debugSummer2Winter) <= debugInterval
        or abs(timeOfDay - debugWinter2Summer) <= debugInterval ):
        dataHour = timeOfDay.hour
        if dataHour >= 14:
            return True
    return False

def DebugThisDay( timeOfDay, year, month, day ):
    if timeOfDay.year == year and timeOfDay.month == month and timeOfDay.day == day:
        return True
    return False

class   HomeSolar(tkinter.Tk):
    def __init__( self ):
        super().__init__()
        self.title('Main Window')
        self.hourlyData = []
        self.options = []
        plt.style.use('bmh')
        self.geometry( '300x200' )
 
        #button_ax = plt.axes([0.8, 0.05, 0.1, 0.075])
        button = tkinter.Button(master=self, text='Select Date', command=select_date)
        button.pack()
        #button = Button(button_ax, text='Select Date', color='xkcd:celery')

    def PlotOptions( self ):
        #plt.clf()
        for option in self.options:
            option.PlotOption()

    def AddOption( self, option, verbose=False ):
        global SelectedDay
        self.options.append( option )
        if verbose:
            print( f'\nAdding option: {option}' )
        battery = option.MaxBattery / 2
        option.Projections.append( HourlyProj( time=self.hourlyData[0].TimeOfDay, battery=battery ) )
        diagTotals = HourlyProj()
        diagDay  = HourlyProj()
        SelectedDay = datetime.datetime(    year=self.hourlyData[0].TimeOfDay.year,
                                            month=self.hourlyData[0].TimeOfDay.month,
                                            day=self.hourlyData[0].TimeOfDay.day )
        #self.hourlyProj = []
        priorDay = 0
        dailyTotal = 0
        for data in self.hourlyData:
            oldSolar = -data.SolarProd
            if oldSolar < 0.02: oldSolar = 0 # Clean up output by eliminating trivial solar kWh due to CT accuracy limits
            newSolar = oldSolar * (option.NewSolarProd / oldSolarYearlyProd)

            if  priorDay != data.TimeOfDay.day:
                priorDay = data.TimeOfDay.day
                dailyTotal = 0
                if diagDay.Grid or diagDay.Charging or diagDay.Export:
                    print( f"DiagDay:\n{diagDay}" )
                diagDay = HourlyProj(time=data.TimeOfDay)
            #verboseDay = False # DebugPeakVsOffPeakTimes(data.TimeOfDay)
            verboseDay = DebugThisDay( data.TimeOfDay, SelectedDay.year, SelectedDay.month, SelectedDay.day )

            newHour = HourlyProj( time=data.TimeOfDay, grid=data.Usage, usage=data.Usage, battery=battery,
                                oldExcess=oldSolar, newExcess=newSolar, oldSolar=oldSolar, newSolar=newSolar )
            #if verboseDay: print( newHour )
            if isPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle Peak periods
                #
                # Use NewSolar first
                newHour.ApplyNewSolarToGrid( )
                if option.NEM == '1.0':
                    # Battery then OldSolar
                    newHour.ApplyBatteryToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    # OldSolar then Battery
                    newHour.ApplyOldSolarToGrid( )
                    newHour.ApplyBatteryToGrid( )
            elif isPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle PartialPeak periods
                #
                # Rough estimate of upcoming 5 hours of peak usage
                estPeakUsage = data.Usage * 5.5
                newHour.ApplyNewSolarToGrid( )
                if option.NEM == '1.0':
                    # Only use battery for 3-4pm partial peak if we can cover peak usage too
                    if data.TimeOfDay.hour != 15 or newHour.Battery <= data.Usage + estPeakUsage:
                        newHour.ApplyBatteryToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    newHour.ApplyOldSolarToGrid( )
                    # Only use battery if we can cover peak usage too
                    if data.TimeOfDay.hour != 15 or newHour.Battery <= data.Usage + estPeakUsage:
                        newHour.ApplyBatteryToGrid( )
            elif isOffPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle OffPeak periods
                #
                #newHour.ApplyNewSolarToGrid( )
                newHour.ApplyOldSolarToGrid( )
                newHour.ApplyNewSolarToGrid( )

                newHour.ApplyNewSolarToBattery( option )
                if option.NewSolarProd == 0 or option.NEM == '3.0':
                    # If we add new solar under NEM 1.0 via non-export, 
                    # we can only charge the battery from NewSolar
                    newHour.ApplyOldSolarToBattery( option )

                # Apply remaining battery to grid
                newHour.ApplyBatteryToGrid( )

            # Apply remaining peak or partial peak NewSolar to battery
            newHour.ApplyNewSolarToBattery( option )

            # Export excess solar to grid
            newHour.ExportOldSolarToGrid( )
            if True or option.NEM == '3.0':
                newHour.ExportNewSolarToGrid( )
            newHour.TimeOfDay += timedelta( minutes=59, seconds=59 )
 
            # Determine costs for this hour
            newHour.DetermineCost( option, dailyTotal )

            # Hold remaining battery for next hour
            battery = newHour.Battery
            diagTotals = diagTotals + newHour
            if verboseDay:
                diagDay = diagDay + newHour
                print( newHour )

            # Add newHour to computed projections
            option.Projections.append( newHour )

        # Compute yearly costs, paypack period, and 25 year savings
        option.ComputeYearlyCosts()

        print( f'\nProjections for: {option}' )

        if True and (diagTotals.Grid or diagTotals.Charging or diagTotals.Export):
            print( f"DiagTotals:         {diagTotals}" )

        if not verbose:
            return

        # Compute average hourly data for Summer, Winter, and diagMonth
        diagMonth = 8
        diagMonthDays = None
        priorDay = 0
        YearlyTotals            = HourlyProj(battery=option.MaxBattery)
        SummerTotals            = HourlyProj(battery=option.MaxBattery)
        SummerPeakTotals        = HourlyProj(battery=option.MaxBattery)
        SummerPartialPeakTotals = HourlyProj(battery=option.MaxBattery)
        SummerOffPeakTotals     = HourlyProj(battery=option.MaxBattery)
        WinterTotals            = HourlyProj(battery=option.MaxBattery)
        WinterPeakTotals        = HourlyProj(battery=option.MaxBattery)
        WinterPartialPeakTotals = HourlyProj(battery=option.MaxBattery)
        WinterOffPeakTotals     = HourlyProj(battery=option.MaxBattery)
        diagMonthTotals         = HourlyProj(battery=option.MaxBattery)
        for newHour in option.Projections:
            YearlyTotals = YearlyTotals + newHour
            if isSummerTime( newHour.TimeOfDay ):
                SummerTotals = SummerTotals + newHour
            if isSummerPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerPeakTotals = SummerPeakTotals + newHour
            if isSummerPartialPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerPartialPeakTotals = SummerPartialPeakTotals + newHour
            if isSummerOffPeakTime( newHour.TimeOfDay, option.RatePlan ):
                SummerOffPeakTotals += newHour
            if isWinterTime( newHour.TimeOfDay ):
                WinterTotals += newHour
            if isWinterPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterPeakTotals += newHour
            if isWinterPartialPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterPartialPeakTotals += newHour
            if isWinterOffPeakTime( newHour.TimeOfDay, option.RatePlan ):
                WinterOffPeakTotals += newHour
            if newHour.TimeOfDay.month == diagMonth:
                diagMonthTotals += newHour
                if not diagMonthDays:
                    diagMonthFirstDay, diagMonthDays = calendar.monthrange( newHour.TimeOfDay.year, diagMonth )
        SummerAvg            = SummerTotals / (365 * 4 / 12)
        SummerPeakAvg        = SummerPeakTotals / (365 * 4 / 12)
        SummerPartialPeakAvg = SummerPartialPeakTotals / (365 * 4 / 12)
        SummerOffPeakAvg     = SummerOffPeakTotals / (365 * 4 / 12)
        WinterAvg            = WinterTotals / (365 * 8 / 12)
        WinterPeakAvg        = WinterPeakTotals / (365 * 8 / 12)
        WinterPartialPeakAvg = WinterPartialPeakTotals / (365 * 8 / 12)
        WinterOffPeakAvg     = WinterOffPeakTotals / (365 * 8 / 12)
        diagMonthAvg         = diagMonthTotals / diagMonthDays
        print( f"Yearly      Totals: {YearlyTotals}" )
        print( f"Summer      Totals: {SummerTotals}" )
        print( f"Summer Peak Totals: {SummerPeakTotals}" )
        print( f"Summer PaPk Totals: {SummerPartialPeakTotals}" )
        print( f"Summer OffP Totals: {SummerOffPeakTotals}" )
        print( f"Summer         Avg: {SummerAvg}" )
        print( f"Summer Peak    Avg: {SummerPeakAvg}" )
        print( f"Summer PaPk    Avg: {SummerPartialPeakAvg}" )
        print( f"Summer OffP    Avg: {SummerOffPeakAvg}" )

        print( f"Winter      Totals: {WinterTotals}" )
        print( f"Winter         Avg: {WinterAvg}" )
        print( f"Winter Peak    Avg: {WinterPeakAvg}" )
        print( f"Winter PaPk    Avg: {WinterPartialPeakAvg}" )
        print( f"Winter OffPeak Avg: {WinterOffPeakAvg}" )
        print( f"{calendar.month_name[diagMonth]}     Totals: {diagMonthTotals}" )

    def ProcessDataFiles( self, pgeData, vueData, verbose = False ):
        # Note: Both data files have 23 entries for start of DST, 3/10/24
        # pgeData has 24 entries for DST, 11/3/24
        # vueData has 25 entries, but we add 1 min to the duplicate 1:00 am as
        # 11/3/24 actually lasts for 25 hours.
        # vueData also includes an extra entry for midnight on the day after the last export day
        # i.e.  Exporting 1/1/24 to 12/31/24 includes an entry for 1/1/25 00:00
        usage = 0
        extraHour  = max(vueData.keys())
        for hourTime, solarProd in vueData.items():
            if hourTime in pgeData:
                usage = pgeData[hourTime]
            # solarProd is negative and needs to be combined
            # with PGE usage to reflect actual usage w/o solar
            usage = max( 0, usage - solarProd )
            if hourTime < extraHour:
                self.hourlyData.append( HourlyData( usage, solarProd, hourTime ) )
        if verbose:
            print( 'Processed %u hourly usage and solarProd values.' % len(self.hourlyData) )
            print( 'From %s to %s' % ( self.hourlyData[0].TimeOfDay.strftime('%m/%d/%Y, %H:%M'),
                                       self.hourlyData[-1].TimeOfDay.strftime('%m/%d/%Y, %H:%M') ) )

def readPgeData( pgeDataFile, verbose=False ):
    pgeData = {}
    try:
        in_file = open( pgeDataFile, 'r' )
        blankLine = in_file.readline()
        nameLine = in_file.readline()
        if nameLine.split(',')[0] != 'Name':
            print( '2nd line in PGE Data File should be Name of acct owner, not\n%s\n' % nameLine )
        if verbose:
            print( nameLine )
        addrLine = in_file.readline()
        if addrLine.split(',')[0] != 'Address':
            print( '3rd line in PGE Data File should be Address of acct owner, not\n%s\n' % addrLine )
        acctLine = in_file.readline()
        if acctLine.split(',')[0] != 'Account Number':
            print( '4th line in PGE Data File should be Account Number, not\n%s\n' % acctLine )
        svcLine  = in_file.readline()
        if svcLine.split(',')[0] != 'Service':
            print( '5th line in PGE Data File should be Service, not\n%s\n' % svcLine )
        blankLine = in_file.readline()

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (pgeDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

    csv_reader = csv.DictReader(in_file)

    numRows = 0
    rowTime = datetime.datetime.now()
    for row in csv_reader:
        numRows = numRows+1
        rowDate = dateutil.parser.parse( row['DATE'] )
        rowStart = dateutil.parser.parse( row['START TIME'] )
        rowEnd   = dateutil.parser.parse( row['END TIME'] )
        if 'USAGE (kWh)' in csv_reader.fieldnames:
            usage = float( row['USAGE (kWh)'])
        else:
            usage = float( row['IMPORT (kWh)'])
            usage -= float( row['EXPORT (kWh)'])

        rowTime = rowDate + datetime.timedelta(hours=rowStart.hour, minutes=rowStart.minute)
        if rowTime in pgeData:
            rowTime = rowTime + datetime.timedelta(minutes=1)
        pgeData[rowTime] = usage
        if verbose and len(pgeData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), usage ) )
    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), usage ) )

    return pgeData

def readVueData( vueDataFile, verbose=False ):
    vueData = {}
    try:
        in_file = open( vueDataFile, 'r' )

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (vueDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

    csv_reader = csv.DictReader(in_file)
    numRows = 0
    rowTime = datetime.datetime.now()
    for row in csv_reader:
        numRows = numRows+1
        rowTime = dateutil.parser.parse( row[vueDateLabel] )
        if vueSolarLabel in csv_reader.fieldnames:
            solarOutput = float( row[vueSolarLabel])
        if rowTime in vueData:
            rowTime = rowTime + datetime.timedelta(minutes=1)
        vueData[rowTime] = solarOutput
        if verbose and len(vueData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    return vueData

def process_options(argv):
    if argv is None:
       argv = sys.argv[1:]
    desc = 'processPgeData reads PGE data files and analyses them.'
    parser = argparse.ArgumentParser( description = desc )
    parser.add_argument( '-f', '--pgeDataFiles', dest='pgeDataFiles', action='append', \
            help='Read PGE Data File -f pgeDataFile1.csv [-f pgeDataFile2.csv]' )
    parser.add_argument( '-e', '--vueDataFiles', dest='vueDataFiles', action='append', \
            help='Read Emporia Vue data file.' )
    parser.add_argument( '-v', '--verbose', action='store_true', help='show verbose diags' )
    options = parser.parse_args()
    return options

# Create myHomeSolar
myHomeSolar = None

def main(argv=None):
    options = process_options(argv)

    if options.pgeDataFiles:
        for pgeDataFile in options.pgeDataFiles:
            newData = readPgeData( pgeDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" PGE Data Points' % len(newData) )
            pgeData.update(newData)

    if options.verbose:
        print( 'Total "%u" PGE Data Points' % len(pgeData) )
        print( 'From %s to %s' % ( min(pgeData.keys()).strftime('%m/%d/%Y, %H:%M'),
                                   max(pgeData.keys()).strftime('%m/%d/%Y, %H:%M') ) )

    if options.vueDataFiles:
        for vueDataFile in options.vueDataFiles:
            newData = readVueData( vueDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" VUE Data Points' % len(newData) )
            vueData.update(newData)

    if options.verbose:
        print( 'Total "%u" VUE Data Points' % len(vueData) )
        print( 'From %s to %s' % ( min(vueData.keys()).strftime('%m/%d/%Y, %H:%M'),
                                   max(vueData.keys()).strftime('%m/%d/%Y, %H:%M') ) )

    global myHomeSolar
    myHomeSolar = HomeSolar()
    myHomeSolar.ProcessDataFiles( pgeData, vueData, options.verbose )

    print("Current PGE Rate Plan Costs")
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-TOU-D', '1.0', 0, 0, 0 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-TOU-C', '1.0', 0, 0, 0 ), verbose=options.verbose )
    print("\nNEM 1.0 options")
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 13.5, 0, 14000 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 13.5, 5600, 22000 ), verbose=options.verbose )
    myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 13.5, 10000, 27500 ), verbose=options.verbose )
    myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 13.5, 11214, 29582 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 27.0, 11214, 29582 + 9800 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 13.5, 14225, 52426*0.70), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '1.0', 27.0, 14636, 65426*0.70), verbose=options.verbose )
    #print("\nNEM 3.0 options")
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '3.0', 13.5, 11214, 29582 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '3.0', 27.0, 11214, 29582 + 9800 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '3.0', 40.5, 11214, 29582 + 9800 + 9800 ), verbose=options.verbose )
    #myHomeSolar.AddOption( Option( myHomeSolar, 'E-ELEC', '3.0', 27.0, 16000, 35000 + 9800 ), verbose=options.verbose )

    # Get handle for Tkinter root window and hide it
    #global root
    #root = tkinter.Tk()
    #root.withdraw()

    # Plot each option
    myHomeSolar.PlotOptions()

    #fig = plt.figure( "Solar and Battery Analysis", figsize=(14,40) )
    #ax = plt.subplot( 1, 2, 1 )

    #plt.show()
    myHomeSolar.mainloop()
    #print( "Starting IPython shell..." )
    #IPython.embed()
    return 0

if __name__ == '__main__':
    status = main()
    sys.exit(status)

