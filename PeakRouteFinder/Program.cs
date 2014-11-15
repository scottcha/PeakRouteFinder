using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Device.Location;
namespace PeakRouteFinder
{
    public class Program
    {
        public List<List<double>> distanceLookup { get; set; }
        public List<Peak> peaks { get; set; }
        public List<List<Peak>> solutions { get; set; }
        int maxDistance = 70; 
        long progressCounter = 0;
        public Stack<Peak> visited { get; set; }
        static void Main(string[] args)
        {
            var fileName = args[0];

            var p = new Program();
            p.FindRoutes(fileName);
        }

        private void ReadPeaksFromFile(string fileName)
        {
            string[] lines = System.IO.File.ReadAllLines(fileName);
            bool firstLine = true;

            foreach (string line in lines)
            {
                if (firstLine)
                {
                    firstLine = false;
                    continue;
                }
                string[] lineComponents = line.Split(',');
                Debug.Assert(lineComponents.Length == 3);
                peaks.Add(new Peak() { name = lineComponents[2], lat = float.Parse(lineComponents[0]), lon = float.Parse(lineComponents[1]) });
            }
        }

        public void FindRoutes(string fileName)
        {
            peaks = new List<Peak>();
            visited = new Stack<Peak>();
            solutions = new List<List<Peak>>();
            ReadPeaksFromFile(fileName);
            InitializeDistanceLookup(peaks);
            //PrintPeakDistances(peaks);
            for (int count = 0; count < peaks.Count; count++)
            {
                Console.WriteLine("\n" + count + " Working on peak " + peaks[count].name);
                progressCounter = 0;
                FindRoutesForPeak(peaks[count], maxDistance);
                solutions.Sort(CompareListsByLength);
                //purge all but the best solution for this peak
                int lengthOfBestCurrentSolution = solutions[0].Count;
                for (int solutionCount = 0; solutionCount < solutions.Count; solutionCount++)
                {
                    if(solutions[solutionCount].Count < lengthOfBestCurrentSolution)
                    {
                        solutions.RemoveAt(solutionCount);
                    }
                }
                visited.Clear();
            }
            using (System.IO.StreamWriter file = new System.IO.StreamWriter("Solutions.csv"))
            {
                int solutionCount = 1;
                foreach(var solution in solutions)
                {
                    for(int peakCount = 0; peakCount < solution.Count; peakCount++)
                    {
                        if(peakCount < solution.Count-1)
                        {
                            file.WriteLine(solutionCount + ", " + solution[peakCount].ToString() + ", " +  CalculateDistance(solution[peakCount], solution[peakCount + 1]));
                        }
                        else
                        {
                            file.WriteLine(solutionCount + ", " + solution[peakCount].ToString()); 
                        }
                    }
                    solutionCount++;
                }
            }
        }

        private static int CompareListsByLength(List<Peak> a, List<Peak> b)
        {
            if (a.Count == b.Count)
            {
                return 0;
            }
            else if (a.Count > b.Count)
            {
                return -1;
            }
            else
            {
                return 1;
            }
        }

        public void InitializeDistanceLookup(List<Peak> peaks)
        {
            distanceLookup = new List<List<double>>();
            for (int p1 = 0; p1 < peaks.Count; p1++)
            {
                distanceLookup.Add(new List<double>());
                for (int p2 = 0; p2 < peaks.Count; p2++)
                {
                    distanceLookup[p1].Add(CalculateDistance(peaks[p1], peaks[p2]));
                }
            }
        }

        public static double CalculateDistance(Peak peak1, Peak peak2)
        {
            //http://stackoverflow.com/questions/6366408/calculating-distance-between-two-latitude-and-longitude-geocoordinates 
            return MetersToMiles(peak1.geoCoordinate.GetDistanceTo(peak2.geoCoordinate));
        }

        public static double MetersToMiles(double distance)
        {
            const double metersToMilesConstant = 0.000621371192;
            return distance * metersToMilesConstant;
        }
        public void PrintPeakDistances(List<Peak> peaks)
        {
            using (System.IO.StreamWriter file = new System.IO.StreamWriter("PeakDistances.csv"))
            {
                //first column has blank header
                file.Write(", ");
                foreach (Peak p in peaks)
                {
                    //write the column headers
                    file.Write(p.name + ", ");
                }
                file.Write("\n");

                //now write the row header then row values
                for (int p1 = 0; p1 < peaks.Count; p1++)
                {
                    //first the row name
                    file.Write(peaks[p1].name + ", ");
                    for (int p2 = 0; p2 < peaks.Count; p2++)
                    {
                        //now the row values
                        if (p2 != peaks.Count - 1)
                        {
                            file.Write(distanceLookup[p1][p2] + ", ");
                        }
                        else
                        {
                            file.Write(distanceLookup[p1][p2] + "\n");
                        }
                    }
                }
                file.Close();
            }
        }

        public void FindRoutesForPeak(Peak p, double distance)
        {
            if (progressCounter++ % 100000 == 0)
            {
                Console.Write(".");
            }
            visited.Push(p);
            var nextPeaks = GetPeaksWithinDistanceNotVisited(p, visited, distance);

            if (nextPeaks.Count == 0)
            {
                //add to solutions
                if (solutions.Count > 0)
                {
                    if (solutions[0].Count <= visited.Count)
                    {
                        //always keep longest solutions in front
                        solutions.Insert(0, visited.ToList());
                    }
                }
                else
                {
                    solutions.Add(visited.ToList());
                }
                visited.Pop();
                return;
            }

            foreach (Peak next in nextPeaks)
            {
                FindRoutesForPeak(next, distance - CalculateDistance(p, next));
            }
            visited.Pop();
            nextPeaks = null;
            return;
        }

        private void DebugPrint(Peak p, List<Peak> listOfPeaks)
        {
            for (int count = 0; count < listOfPeaks.Count; count++)
            {
                if (count < listOfPeaks.Count - 1)
                {
                    Debug.WriteLine(" {0}, distance {1} ", listOfPeaks.ToArray()[count].name, CalculateDistance(listOfPeaks.ToArray()[count], p));
                }
                else
                {
                    Debug.WriteLine(" " + listOfPeaks.ToArray()[count].name);
                }
            }
        }

        private double CalculateTotalDistance(List<Peak> listOfPeaks)
        {
            double sum = 0.0;
            for(int count = 0; count < listOfPeaks.Count-1; count++)
            {
                sum += CalculateDistance(listOfPeaks[count], listOfPeaks[count + 1]);
            }
            return sum;
        }
        public List<Peak> GetPeaksWithinDistanceNotVisited(Peak p, Stack<Peak> visited, double distance)
        {
            int index = peaks.IndexOf(p);
            var lookups = distanceLookup[index];
            var returnValues = new List<Peak>();
            for (int i = 0; i < lookups.Count; i++)
            {
                if (lookups[i] < distance)
                {
                    if (visited.Contains(peaks[i]) || peaks[i].Equals(p))
                    {
                        continue;
                    }
                    else
                    {
                        returnValues.Add(peaks[i]);
                    }
                }
            }
            return returnValues;
        }


    }
}
