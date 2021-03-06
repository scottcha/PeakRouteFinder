﻿using System;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using PeakRouteFinder;
using System.Collections.Generic;
namespace PeakRouteFinderTests
{
    [TestClass]
    public class ProgramTests
    {
        Program p;
        List<Peak> peaks;
        [TestInitialize]
        public void Initialize()
        {
            p = new Program();
            peaks = new List<Peak>() {
                                            new Peak{lat = 41, lon = 121}, 
                                            new Peak{lat = 41, lon = -121},
                                            new Peak{lat = 41, lon = 121}
                                        };
            p.visited = new Stack<Peak>();
        }

        [TestMethod]
        public void TestPeakInitialize()
        {
            p.InitializeDistanceLookup(peaks);
            Assert.AreEqual(p.distanceLookup[0][0], p.distanceLookup[0][2]);
            Assert.AreNotEqual(p.distanceLookup[0][1], p.distanceLookup[0][2]);
        }
           
        [TestMethod]
        public void TestGetPeaksWithinDistanceNotVisited()
        {
            p.peaks = peaks;
            p.InitializeDistanceLookup(peaks);
            var result = p.GetPeaksWithinDistanceNotVisited(peaks[0], 10);
            Assert.AreEqual(result.Count, 1);
            result = p.GetPeaksWithinDistanceNotVisited(peaks[1], 10);
            Assert.AreEqual(result.Count, 0);
        }
    }
}
